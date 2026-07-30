#!/usr/bin/env python3
"""THE spell checker for every text-entry surface in `apps/`.

surfer needs none of this — QtWebEngine has Chromium's own checker, wired
imperatively in `_wire_profile` against an `en-US.bdic` (see
`apps/surfer/AGENTS.md`). That machinery is browser-only: a plain QML
`TextEdit`/`TextArea`/`TextInput` has no spellchecking of any kind, so the
other apps need a real implementation. This is it, and it is deliberately ONE
implementation — a second copy would disagree with the first about what a word
is inside a week.

**hunspell, in pipe mode, over a subprocess.** `hunspell -a` speaks the ispell
protocol: write `^word`, read one result line plus a blank one. That buys the
real affix engine (so `walked`, `walking`, `unwalkable` are all one stem) and
hunspell's own suggestion ranking, with no Python binding to package — and
`python3-enchant`/`pyhunspell` are not a given on Fedora, which is what book
is. The alternative considered and rejected was reading `en_US.dic` in Python:
the word list alone is not the dictionary (it is stems plus affix flags), so
"colour is wrong but coloured is fine" would have been the result.

**The dictionary source is the same one surfer's `.bdic` is compiled from** —
`pkgs.hunspellDicts.en_US` — so the two never disagree about a word, and
`en_US` here is the same language as surfer's `en-US`.

**If the dictionary is missing at runtime, nothing is marked.** [docs/DESIGN.md §10]
An input must behave exactly as it does today rather than half-underlining
everything, so `available` is false the moment the binary, the dictionary or the
process is not there, and every query answers "fine". That is checked, not
assumed: `apps/pylib/tools/spellcheck-test.py` runs the whole surface with the
binary pointed at nothing.

Environment (set by `home/prog/<app>.nix` on top, resolved from the system on
book):

    SPELL_HUNSPELL   absolute path to the hunspell binary (else `$PATH`)
    SPELL_DICPATH    dir holding `en_US.dic`/`en_US.aff` (else the usual places)
    SPELL_LANG       dictionary basename, default `en_US`
    SPELL_DISABLE    set to any non-empty value to switch the feature off

Personal words live in `$XDG_STATE_HOME/spellcheck/personal.dic`, one per line,
shared by every app — "add to dictionary" in one is added in all of them. It is
consulted before hunspell, so it works even when nothing else does.

QML side: install this as the `Spell` context property (like `DeskStyle`), keep
a Python reference to it, and draw the marks with `qmlcommon/SpellMarks.qml`.
"""

from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot

LANG = os.environ.get("SPELL_LANG") or "en_US"

# Where a dictionary lives when nobody told us. Fedora ships `hunspell-en-US`
# into the first; the second is myspell's older layout, still used by some
# distros' dictionary packages.
_DIC_DIRS = ["/usr/share/hunspell", "/usr/share/myspell/dicts"]

_READ_TIMEOUT = 3.0  # seconds to wait for one answer before declaring it dead

# A word is letters, with internal apostrophes ("doesn't", "developer's").
# Digits and `_` are word BREAKS on purpose: `sha256sum` is not three words to
# be judged, it is a token to be left alone, and `_neighbour()` catches it.
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)

# Characters that make the thing a word sits in an identifier, a path, a URL or
# a version rather than prose. A digit counts: `mp3` and `utf8` are not words.
_CODEY = set("\\/._@:#$&=%+<>|~`^*0123456789")


def _state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "spellcheck"


def words(text: str, start: int = 0, end: int | None = None):
    """Yield `(start, end, word)` for every token in `text[start:end]` that is
    worth judging. Skipped, and why:

      * shorter than three letters — `a`, `an`, `of` carry no information and a
        two-letter miss is almost always a deliberate abbreviation;
      * ALL CAPS — an acronym (`QML`, `NIXOS`, `TODO`), which no en_US
        dictionary knows and which is not a spelling mistake;
      * an inner capital — `positionAt`, `PromptBox`: an identifier, and the
        one shape that would underline half of a code comment;
      * touching a `_CODEY` character — `os.path`, `en_US`, `mp3`, `x=1`.

    Those four rules are what keeps this usable in a text editor. Without them
    the first paste of a log line lights up the whole document, and a marker
    that is wrong that often is one he will ask to have removed.
    """
    if end is None or end > len(text):
        end = len(text)
    if start < 0:
        start = 0
    for m in _WORD.finditer(text, start, end):
        w = m.group(0)
        if len(w) < 3:
            continue
        if w.isupper():
            continue
        if any(c.isupper() for c in w[1:]):
            continue
        if _neighbour(text, m.start(), m.end()):
            continue
        yield m.start(), m.end(), w


def _neighbour(text: str, s: int, e: int) -> bool:
    """True when the character on either side of the token makes it part of
    something that is not prose. A trailing `.` only counts when a letter
    follows it — otherwise every sentence's last word would be skipped."""
    if s > 0 and text[s - 1] in _CODEY:
        return True
    if e < len(text):
        nxt = text[e]
        if nxt in _CODEY:
            # `end.` at the close of a sentence is prose; `os.path` is not.
            if nxt in "._" and (e + 1 >= len(text) or not text[e + 1].isalnum()):
                return False
            return True
    return False


class _Hunspell:
    """One `hunspell -a` child, started on first use and never restarted.

    A dead child means `available` goes false and stays false for the life of
    the app: a checker that silently retried would spawn a process per
    keystroke on a broken machine. Every answer is cached, so a document's
    second pass costs nothing.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._buf = b""
        self._lock = threading.Lock()
        self._dead = bool(os.environ.get("SPELL_DISABLE"))
        self._started = False
        self._ok: dict[str, bool] = {}
        self._sug: dict[str, list[str]] = {}
        self._personal: set[str] = set()
        self._load_personal()

    # ---------------------------------------------------------------- personal
    def _personal_path(self) -> Path:
        return _state_dir() / "personal.dic"

    def _load_personal(self) -> None:
        try:
            for line in self._personal_path().read_text("utf-8").splitlines():
                w = line.strip()
                if w:
                    self._personal.add(w.lower())
        except OSError:
            pass

    def learn(self, word: str) -> None:
        w = word.strip()
        if not w:
            return
        self._personal.add(w.lower())
        self._ok.pop(w, None)
        try:
            p = self._personal_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(w + "\n")
        except OSError:
            # The word still counts for this session; a failure to persist must
            # not make "add to dictionary" look like it did nothing.
            pass

    def forget_all(self) -> None:
        self._personal.clear()
        self._ok.clear()

    # ------------------------------------------------------------------ engine
    def _dicpath(self) -> str | None:
        env = os.environ.get("SPELL_DICPATH")
        cands = [env] if env else []
        for d in os.environ.get("XDG_DATA_DIRS", "").split(":"):
            if d:
                cands.append(os.path.join(d, "hunspell"))
        cands += _DIC_DIRS
        for d in cands:
            if d and os.path.exists(os.path.join(d, LANG + ".dic")):
                return d
        return None

    def _start(self) -> None:
        self._started = True
        binary = os.environ.get("SPELL_HUNSPELL") or shutil.which("hunspell")
        dicpath = self._dicpath()
        if not binary or not os.path.exists(binary) or not dicpath:
            self._dead = True
            return
        env = dict(os.environ)
        env["DICPATH"] = dicpath
        env["LC_ALL"] = "C.UTF-8"
        try:
            # UNBUFFERED, and bytes. `select` on a buffered text stream is a
            # trap: `readline()` pulls the whole 4k chunk into Python's own
            # buffer, so the NEXT select sees an idle fd and times out with the
            # answer already in hand — which read as "hunspell is dead" for
            # every misspelling and silently disabled the checker.
            self._proc = subprocess.Popen(
                [binary, "-a", "-i", "UTF-8", "-d", LANG],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env, bufsize=0,
            )
            banner = self._readline()
            if not banner or not banner.startswith("@(#)"):
                raise OSError("no ispell banner: %r" % banner)
        except (OSError, ValueError):
            self._kill()

    def _kill(self) -> None:
        self._dead = True
        p, self._proc = self._proc, None
        if p is not None:
            try:
                p.kill()
            except OSError:
                pass

    def _readline(self) -> str:
        """One line, or "" — and a stall is a death, not a hang. The GUI thread
        calls this, so a wedged child must never be able to freeze a window.
        The buffer is ours (see `_start`), so a line already read is a line
        already available."""
        p = self._proc
        if p is None or p.stdout is None:
            return ""
        while b"\n" not in self._buf:
            r, _, _ = select.select([p.stdout], [], [], _READ_TIMEOUT)
            if not r:
                raise OSError("hunspell timed out")
            chunk = os.read(p.stdout.fileno(), 4096)
            if not chunk:
                raise OSError("hunspell closed its pipe")
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode("utf-8", "replace") + "\n"

    @property
    def available(self) -> bool:
        if not self._started and not self._dead:
            with self._lock:
                if not self._started:
                    self._start()
        return not self._dead

    def check(self, word: str) -> bool:
        if word.lower() in self._personal:
            return True
        hit = self._ok.get(word)
        if hit is not None:
            return hit
        self._query(word)
        return self._ok.get(word, True)

    def suggest(self, word: str) -> list[str]:
        if word.lower() in self._personal:
            return []
        if word not in self._sug:
            self._query(word)
        return self._sug.get(word, [])

    def _query(self, word: str) -> None:
        if not self.available:
            self._ok[word] = True
            self._sug[word] = []
            return
        with self._lock:
            if self._dead or self._proc is None or self._proc.stdin is None:
                self._ok[word] = True
                self._sug[word] = []
                return
            try:
                # `^` protects the word from ispell's own command characters —
                # a line starting `*` or `#` would ADD to the dictionary.
                self._proc.stdin.write(("^" + word + "\n").encode("utf-8"))
                self._proc.stdin.flush()
                good, sugs = True, []
                while True:
                    line = self._readline()
                    if line in ("", "\n", "\r\n"):
                        break
                    code = line[0]
                    if code in "&?":
                        good = False
                        _, _, tail = line.partition(":")
                        sugs = [s.strip() for s in tail.split(",") if s.strip()]
                    elif code == "#":
                        good = False
                if len(self._ok) > 20000:      # a session's worth; not a leak
                    self._ok.clear()
                    self._sug.clear()
                self._ok[word] = good
                self._sug[word] = sugs
            except (OSError, ValueError):
                self._kill()
                self._ok[word] = True
                self._sug[word] = []


_ENGINE = _Hunspell()


def engine() -> _Hunspell:
    return _ENGINE


def spans(text: str, start: int = 0, end: int | None = None,
          limit: int = 4000) -> list[list[int]]:
    """`[[start, end], ...]` for the misspelled words in `text[start:end]`.

    `limit` caps how many words are judged in one call, so a 200k-line paste
    cannot stall the frame it lands in. Callers that have a viewport pass the
    visible range and never approach it.
    """
    if not _ENGINE.available:
        return []
    out: list[list[int]] = []
    n = 0
    for s, e, w in words(text, start, end):
        n += 1
        if n > limit:
            break
        if not _ENGINE.check(w):
            out.append([s, e])
    return out


def word_at(text: str, pos: int) -> tuple[int, int, str]:
    """The word `pos` sits in or beside, as `(start, end, word)`; `(-1, -1, "")`
    if there is none. Right-clicking a word puts the caret at its edge as often
    as inside it, so both edges count."""
    if pos < 0 or pos > len(text):
        return -1, -1, ""
    lo = max(0, pos - 64)
    for s, e, w in words(text, lo, min(len(text), pos + 64)):
        if s <= pos <= e:
            return s, e, w
    return -1, -1, ""


class SpellCheck(QObject):
    """The `Spell` context property. Stateless per call; the cache is the
    engine's."""

    availableChanged = Signal()

    @Property(bool, notify=availableChanged)
    def available(self) -> bool:
        return _ENGINE.available

    @Slot(str, int, int, result="QVariantList")
    def spans(self, text: str, start: int = 0, end: int = -1):
        return spans(text, start, None if end < 0 else end)

    @Slot(str, int, result="QVariantMap")
    def wordAt(self, text: str, pos: int):
        s, e, w = word_at(text, pos)
        if s < 0:
            return {"start": -1, "end": -1, "word": "", "bad": False}
        bad = _ENGINE.available and not _ENGINE.check(w)
        return {"start": s, "end": e, "word": w, "bad": bad}

    @Slot(str, result="QStringList")
    def suggest(self, word: str):
        if not _ENGINE.available:
            return []
        # Five is what fits a menu without turning it into a list view; the
        # ranking is hunspell's, so the first is the one it means.
        return _ENGINE.suggest(word)[:5]

    @Slot(str)
    def learn(self, word: str):
        _ENGINE.learn(word)
