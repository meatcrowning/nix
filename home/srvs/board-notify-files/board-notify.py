#!/usr/bin/env python3
"""board-notify — a desktop notification when a spirit's completion lands.

`~/nix/docs/board.<hostname>.md` (one board per host) is where a finishing
worker parks its result: a WAITING ON YOU TO DO bullet tagged COMPLETION — the
"done, no errors. pushed." record. Until this existed, the only way he learned a
worker had finished was opening goetia (or the board-watch timer doing unrelated
work). This closes that gap: when a NEW completion bullet lands, a notification
fires — unless goetia is already the focused window, in which case he is already
looking at the store and the toast would be noise.

Deployed to ~/.config/scripts by home/srvs/board-notify.nix, which also carries
the systemd unit and the reasoning for the mechanism. Read that file first.

WHY A DAEMON AND NOT A PATH UNIT (the sibling board-watch is a path+timer
oneshot): the one half that cannot be a one-shot is FOCUS. Whether goetia has
focus must come from Hyprland's EVENT SOCKET, not from `hyprctl activewindow` —
that call reports `CFocusState::window()`, which `rawSurfaceFocus` never clears
(see the memory `hyprctl-activewindow-lies`): it keeps naming goetia even while
focus is on the panel or nothing, so a one-shot snapshot would wrongly suppress
notifications half the time. `activewindow>>,` (empty payload) on the event
socket is the only honest "focus is on nobody". The socket only pushes on
CHANGE and sends no snapshot on connect (measured on top 2026-08-01), so the
subscription has to be held open by a long-lived process — this one. It keeps
the current focus in memory the whole time it runs; the board watch rides on
the same process rather than a second round of units.

THE TAG IT MATCHES, and the rename it survives: the marker is the bullet's tag,
read from `boardparse.tag_of` — the underlying marker, never the human label.
Currently `COMPLETION`; a parallel spirit is renaming that display/tag to
`ENACTED` right now (2026-08-01). Both words are accepted, and a bullet is ALSO
matched by its raw text leading `COMPLETION:` / `ENACTED:` even if the parser's
tag set has already forgotten one of them, so the rename cannot silently stop
notifications. The dedupe fingerprint strips the leading tag word, so a global
relabel of already-stored bullets cannot re-fire them either.

THE FAILED COUNTERPART. A worker that finishes with nothing landed writes a
`FAILED:` bullet (`boardparse.TODO_TAGS`) into the same WAITING ON YOU TO DO
list, the same shape as a `FAILED`/`ENACTED` result. That case must never
sink quietly under the good news, so it gets its own CRITICAL-urgency toast
instead of the normal one — same dedupe, same goetia-focus suppression, same
raw-text-prefix fallback for a future rename, just a different urgency and a
different tag set (`BOARD_NOTIFY_FAIL_TAGS`, default `FAILED,FAILURE,ERROR`
— `FAILED` is the one the store actually writes today; the other two are
accepted defensively in case a future rename repeats the COMPLETION ->
ENACTED history). The toast names the worker: the bullet's `by:` stamp
(`boardparse.by_now`, whoever's `whoami()` wrote the result) is prefixed onto
the body when present.

ONCE PER NEWLY-LANDED COMPLETION OR FAILURE — mirrored from board-watch's
newly-answered semantics. `~/.local/state/board-notify/state.json` keeps two
sets of fingerprints already recorded (`seen` for completions, `seen_fail`
for failures); a bullet present in the file but not in the matching set is new
and fires (once). A docs-sync pull or an edit that adds no new bullet leaves
`fresh == seen` and changes nothing. The FIRST ever run seeds the whole board
and fires nothing for either kind — waking up to a stack of toasts for results
that predated this feature is not the point — exactly as board-watch seeds
answers.

BOTH MACHINES, HOST-NEUTRAL. `home/` is shared verbatim to book; the daemon
discovers the live Hyprland instance from `$XDG_RUNTIME_DIR/hypr/*` (never
trusting an inherited HYPRLAND_INSTANCE_SIGNATURE — see hypr-env.nix), and
`notify-send` comes from a nix `libnotify` on the unit's PATH, so neither half
cares which host. If no compositor answers (no session, or book on a console),
there is no focus signal — focus is UNKNOWN and the safe default applies: fire
the notification rather than wrongly suppress it, and log why. Notifications
are harmless when he is away or locked, so there is deliberately no board-watch
style at-the-machine gate.

A KILL SWITCH, like board-watch: `touch ~/.local/state/board-notify/off` and
the daemon stops notifying (and logs), no rebuild needed.

TESTING. Everything is overridable by environment, so the filter, the dedupe
and the focus gate can be exercised without a real session or a real board:

    BOARD_NOTIFY_BOARD    store to read      (default: bp.ensure_board())
    BOARD_NOTIFY_STATE    state dir          (default ~/.local/state/board-notify)
    BOARD_NOTIFY_LOG      log file           (default ~/.cache/board-notify.log)
    BOARD_NOTIFY_TAGS     comma tag words    (default COMPLETION,ENACTED)
    BOARD_NOTIFY_FAIL_TAGS comma tag words   (default FAILED,FAILURE,ERROR)
    BOARD_NOTIFY_FOCUS    fake focus "class,title", or "" for "on nothing"
    BOARD_NOTIFY_NOTIFY   command run INSTEAD of notify-send ('' to dry-run)
    BOARD_NOTIFY_POLL     board poll seconds (default 3)
    BOARD_NOTIFY_ONESHOT  run one board pass and exit, no daemon / no focus
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime

HOME = os.path.expanduser("~")
REPO = os.environ.get("BOARD_NOTIFY_REPO", os.path.join(HOME, "nix"))
STATE = os.environ.get("BOARD_NOTIFY_STATE",
                       os.path.join(HOME, ".local", "state", "board-notify"))
LOG = os.environ.get("BOARD_NOTIFY_LOG",
                     os.path.join(HOME, ".cache", "board-notify.log"))
OFF = os.path.join(STATE, "off")
POLL_SECONDS = float(os.environ.get("BOARD_NOTIFY_POLL", "3"))

#: The tag(s) a finishing worker writes — the underlying marker, seeing the
#: parallel COMPLETION -> ENACTED rename in flight (see module docstring).
COMPLETION_TAGS = frozenset(
    t.strip().upper() for t in
    os.environ.get("BOARD_NOTIFY_TAGS", "COMPLETION,ENACTED").split(",")
    if t.strip())
_TAG_LEAD_RE = re.compile(
    r"^\s*[-*+]?\s*(?:%s):" % "|".join(sorted(COMPLETION_TAGS)), re.I)

#: The tag(s) a worker that landed NOTHING writes — `FAILED` is the live word
#: (`boardparse.TODO_TAGS`); `FAILURE`/`ERROR` are accepted defensively in case
#: a future rename repeats the COMPLETION -> ENACTED history (see module
#: docstring).
FAILURE_TAGS = frozenset(
    t.strip().upper() for t in
    os.environ.get("BOARD_NOTIFY_FAIL_TAGS", "FAILED,FAILURE,ERROR").split(",")
    if t.strip())
_FAIL_TAG_LEAD_RE = re.compile(
    r"^\s*[-*+]?\s*(?:%s):" % "|".join(sorted(FAILURE_TAGS)), re.I)

sys.path[:0] = [os.path.join(REPO, "apps", "board"),
                os.path.join(REPO, "apps", "pylib")]
import boardparse as bp                                          # noqa: E402

#: THE BOARD THIS HOST WATCHES, exactly as board-watch resolves it —
#: `os.uname().nodename` -> one board per host, seeded on a machine that has
#: never had one.
BOARD = os.environ.get("BOARD_NOTIFY_BOARD") or bp.ensure_board()


# ---------------------------------------------------------------------------- log
def _rotate():
    try:
        if os.path.getsize(LOG) > 262144:
            with open(LOG, "rb") as f:
                f.seek(-131072, os.SEEK_END)
                tail = f.read()
            with open(LOG, "wb") as f:
                f.write(tail)
    except OSError:
        pass


def log(msg):
    line = datetime.now().astimezone().isoformat(timespec="seconds") + " " + msg
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass
    if sys.stderr.isatty() or os.environ.get("BOARD_NOTIFY_ECHO"):
        print(line, file=sys.stderr)


# ----------------------------------------------------------------- the state
def load_state():
    try:
        with open(os.path.join(STATE, "state.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"version": 1, "seen": {}, "seen_fail": {}, "seeded": False}
    d.setdefault("seen", {})
    d.setdefault("seen_fail", {})
    # EXISTENCE of the file is the evidence of seeding, as in board-watch: only
    # a completed pass writes one, so a state file implies a past seed.
    d.setdefault("seeded", True)
    return d


def save_state(d):
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, ".state.json.tmp")
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, os.path.join(STATE, "state.json"))


# ---------------------------------------------------------- the completion set
def _norm(text):
    return " ".join(str(text).split())


def is_completion(t):
    """Is this WAITING bullet a finishing worker's record?

    Two ways to be one, so the rename cannot outrun us: it parses as one of the
    completion tags, OR its raw first line leads with one of the tag words even
    when the parser's own tag set no longer includes it.
    """
    if (t.get("tag") or "").upper() in COMPLETION_TAGS:
        return True
    return bool(_TAG_LEAD_RE.match(str(t.get("headRaw") or t.get("text") or "")))


def completion_body(t):
    """The human line for the toast — the bullet's first line, tag kept."""
    return _norm(t.get("headRaw") or t.get("text") or "")


def completion_fingerprint(t):
    """Identity for dedupe = the bullet's own text, minus the leading tag word.

    Stripping the tag matters for the rename: a stored COMPLETION bullet that a
    parallel pass re-tags to ENACTED in place must not read as a brand-new
    completion (`fresh == seen` again). The rest is the bullet's content, which
    is written once and stable, so a docs-sync pull re-writing the file with the
    same bullet changes nothing.
    """
    raw = _TAG_LEAD_RE.sub("", _norm(t.get("headRaw") or t.get("raw")
                                     or t.get("text") or ""))
    return raw.strip()


def completions_of(doc):
    """[(fingerprint, body)] for every completion bullet, file order."""
    return [(completion_fingerprint(t), completion_body(t))
            for t in doc.get("todo", []) if is_completion(t)]


# ------------------------------------------------------------- the failure set
def is_failure(t):
    """Is this WAITING bullet a worker's FAILED result? Same two-way match as
    `is_completion`, against `FAILURE_TAGS` instead."""
    if (t.get("tag") or "").upper() in FAILURE_TAGS:
        return True
    return bool(_FAIL_TAG_LEAD_RE.match(str(t.get("headRaw") or t.get("text") or "")))


def failure_body(t):
    """The human line for the toast, worker-named: the bullet's `by:` stamp
    (`boardparse.by_now` — who wrote the result) prefixed when present, so a
    CRITICAL toast never reads as an anonymous failure."""
    body = _norm(t.get("headRaw") or t.get("text") or "")
    who = _norm(t.get("by") or "")
    return "%s - %s" % (who, body) if who else body


def failure_fingerprint(t):
    """Identity for dedupe = the bullet's own text, minus the leading tag word.
    Same reasoning as `completion_fingerprint`; deliberately excludes `by` so a
    later stamp correction on the same bullet does not re-fire it."""
    raw = _FAIL_TAG_LEAD_RE.sub("", _norm(t.get("headRaw") or t.get("raw")
                                          or t.get("text") or ""))
    return raw.strip()


def failures_of(doc):
    """[(fingerprint, body)] for every FAILED bullet, file order."""
    return [(failure_fingerprint(t), failure_body(t))
            for t in doc.get("todo", []) if is_failure(t)]


# -------------------------------------------------------------- focus (socket)
def discover_event_socket():
    """The LIVE instance's `.socket2.sock`, discovered like board-watch's
    `hypr_env()`: scan `$XDG_RUNTIME_DIR/hypr/*` newest-first and verify with
    `hyprctl version`. Returns the event socket path or None."""
    xdg = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    root = os.path.join(xdg, "hypr")
    try:
        sigs = sorted(os.listdir(root), reverse=True)
    except OSError:
        return None
    for sig in sigs:
        if not os.path.exists(os.path.join(root, sig, ".socket.sock")):
            continue
        env = dict(os.environ, HYPRLAND_INSTANCE_SIGNATURE=sig, XDG_RUNTIME_DIR=xdg)
        try:
            p = subprocess.run(["hyprctl", "version"], env=env,
                               capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if p.returncode == 0:
            return os.path.join(root, sig, ".socket2.sock")
    return None


def goetia_name(cls, title):
    """`class` is observed to be `board` (Qt's WM_CLASS) and `title` `goetia`."""
    c = (cls or "").lower()
    t = (title or "").lower()
    return c in ("goetia", "board") or "goetia" in t


class FocusTracker(threading.Thread):
    """Hold the compositor's CURRENT focus, read from the event socket.

    `hyprctl activewindow` is useless here (hyprctl-activewindow-lies); the
    socket is the truth. Subscribed for the process's lifetime, reconnecting
    across compositor reloads/restarts. `.goetia` is what a firing decision
    consults; before the first `activewindow` event (or while no compositor
    answers) focus is UNKNOWN — and unknown is treated as NOT goetia, i.e. the
    notification fires, which is the safe default.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self._lock = threading.Lock()
        self._cls = None
        self._title = None

    def current(self):
        with self._lock:
            return self._cls, self._title

    @property
    def goetia(self):
        cls, title = self.current()
        return goetia_name(cls, title)

    def run(self):
        backoff = 1.0
        while True:
            sock_path = discover_event_socket()
            if sock_path is None:
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            backoff = 1.0
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(60)
                s.connect(sock_path)
                s.sendall(b"subscribe activewindow\n")
                self._read_loop(s)
            except OSError:
                pass
            finally:
                try:
                    s.close()
                except Exception:                                    # noqa: BLE001
                    pass
                with self._lock:
                    # The instance went away: focus is unknown, not "goetia".
                    self._cls = None
                    self._title = None
            time.sleep(0.5)

    def _read_loop(self, s):
        buf = b""
        while True:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return                                  # EOF: compositor gone
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self._handle(line.decode("utf-8", "replace").rstrip("\r"))

    def _handle(self, line):
        if not line.startswith("activewindow>>"):
            return
        _, _, payload = line.partition(">>")
        cls, _, title = payload.partition(",")
        with self._lock:
            self._cls = cls.strip()
            self._title = title.strip()


# ---------------------------------------------------------------------- fire
def notify(body, urgency="normal"):
    stub = os.environ.get("BOARD_NOTIFY_NOTIFY")
    if stub == "":
        log("notify (dry-run) urgency=%s: %s" % (urgency, (body or "")[:120]))
        return
    try:
        if stub:
            subprocess.run(["/bin/sh", "-c", stub], timeout=10)
        else:
            # The desktop-entry hint, because this is the ONE sender whose
            # app name and .desktop id disagree: the program is goetia, the
            # entry is board.desktop. The panel's notifs page enumerates
            # candidates from .desktop files (X-GNOME-UsesNotifications), so
            # without the hint the row it offers would be keyed `board` while
            # this notification arrives as `goetia`, and a rule set on it would
            # silently never fire. `--` before the positionals: a FAILED
            # body's `by:`-prefixed text is worker-controlled and must never
            # be read as another option (notify-send-dash-body memory).
            subprocess.run(["notify-send", "-a", "goetia",
                            "-h", "string:desktop-entry:board",
                            "-u", urgency, "--",
                            "goetia", body or ""],
                           timeout=10)
        log("notified (%s): %s" % (urgency, (body or "")[:120]))
    except (OSError, subprocess.SubprocessError) as e:
        log("could not notify: %s" % e)


# ------------------------------------------------------------- the board pass
def handle_board(state, focus):
    try:
        src = bp.read(BOARD)
    except OSError as e:
        log("cannot read %s: %s" % (BOARD, e))
        return

    doc = bp.parse(src)
    completions = completions_of(doc)
    failures = failures_of(doc)
    seen = state["seen"]
    seen_fail = state["seen_fail"]

    if not state.get("seeded"):
        for fp, _ in completions:
            seen[fp] = True
        for fp, _ in failures:
            seen_fail[fp] = True
        state["seeded"] = True
        save_state(state)
        log("first run: recorded %d completion(s), %d failure(s), fired nothing"
            % (len(completions), len(failures)))
        return

    new = [t for t in completions if t[0] not in seen]
    new_fail = [t for t in failures if t[0] not in seen_fail]
    if not new and not new_fail:
        return                            # nothing newly landed — HAZARD 1/2

    for fp, body in new:
        seen[fp] = True                   # never re-attempt, suppressed or not
        if focus.goetia:
            log("suppressed - goetia is the focused window: %s" % body[:80])
            continue
        notify(body)

    for fp, body in new_fail:
        seen_fail[fp] = True              # never re-attempt, suppressed or not
        if focus.goetia:
            log("suppressed (failure) - goetia is the focused window: %s" % body[:80])
            continue
        notify(body, urgency="critical")

    save_state(state)


def run():
    if os.path.exists(OFF):
        log("off (kill switch %s exists; rm it to re-enable)" % OFF)
        return
    state = load_state()

    if os.environ.get("BOARD_NOTIFY_ONESHOT"):
        fake = os.environ.get("BOARD_NOTIFY_FOCUS")
        focus_cls, _, focus_title = (fake or ",").partition(",")

        class _Fake:
            goetia = goetia_name(focus_cls, focus_title)
        handle_board(state, _Fake())
        return

    focus = FocusTracker()
    focus.start()
    last_mtime = None
    while True:
        if os.path.exists(OFF):
            log("off (kill switch appeared) - stopping")
            return
        try:
            now = os.stat(BOARD).st_mtime_ns
        except OSError:
            now = None
        if now != last_mtime:
            last_mtime = now
            try:
                handle_board(state, focus)
            except Exception as e:                     # noqa: BLE001
                log("board pass failed: %s" % e)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
