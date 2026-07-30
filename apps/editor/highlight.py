#!/usr/bin/env python3
"""editor's syntax layer — the language table and the one QSyntaxHighlighter.

Two things live here and nothing else does: LANGS (what a language IS, to this
editor) and Highlighter (how it is painted). main.py owns the documents; QML
owns the view.

**No theme is hardcoded.** docs/DESIGN.md §3.1 — the wallpaper owns the palette
and nothing picks a colour — so every token class here resolves to a NAMED SLOT
of the live wal palette (`accent`, `ok`, `info`, `dim`, `warn`, `textDim`,
`text`), never to a literal. The palette is monochromatic by construction, so
this is §3.2's two tiers and §3.3's brightness ladder applied to code rather
than to widgets: the bulk of a line sits at `text`, comments fall to `dim`, and
the things you scan FOR (keywords, strings, numbers) ride brighter on top. A
rainbow of invented hues is not available on this desktop and would not survive
a wallpaper change.

`ROLE` is that mapping, in one place, so a retune is one dict and not eight
grammars.

**Regex, per line, and deliberately so.** This is not a parser: `highlightBlock`
sees one block at a time, and the only cross-block state carried is the
"am I inside a fenced/multi-line construct" integer QSyntaxHighlighter gives us
(`setCurrentBlockState`) — used for C-style `/* */`, Python/Lua long strings and
markdown fences. That is enough for every language this repo is written in and
it stays O(line). Anything that needs a real grammar (nested Nix antiquotation
inside a string inside an interpolation) is deliberately out of scope; it
mis-paints, it never hangs.

**The search highlight rides in the same pass** (`set_query`). It is not a
second overlay: a match's background is merged onto whatever the syntax pass
already put there, so all matches are lit at once — the find bar's "highlight
all" — with no geometry arithmetic in QML and no second scan of the document.
"""
import re

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat


# ---------------------------------------------------------------- token roles
# token class -> palette slot name (resolved live against WalPalette).
ROLE = {
    "keyword":  "accent",
    "builtin":  "info",
    "type":     "info",
    "string":   "ok",
    "number":   "info",
    "comment":  "dim",
    "meta":     "warn",      # decorators, preprocessor, front matter, shebang
    "punct":    "textDim",
    "heading":  "accent",
    "emph":     "text",
}


def _kw(words):
    """A word-boundary alternation for a keyword list, longest first so `elif`
    is not eaten by `el`. Built once per language at import."""
    ws = sorted(set(words.split()), key=len, reverse=True)
    return r"\b(?:" + "|".join(re.escape(w) for w in ws) + r")\b"


# ------------------------------------------------------------- the languages
# Each entry:
#   name      what the footer and the language menu call it
#   exts      filename extensions (lowercase, with the dot)
#   names     exact basenames (Makefile, flake.lock, ...)
#   shebang   regex matched against a `#!` first line
#   line      line-comment prefix, or "" if the language has none (the
#             comment/uncomment action then REFUSES rather than inventing one —
#             docs/DESIGN.md §10.2)
#   block     (open, close) for a block comment, or None
#   indent    default indent width, in columns
#   tabs      True if this language indents with hard tabs by default
#   rules     [(compiled regex, token class)] applied in order; the FIRST rule
#             that claims a span wins, so strings and comments come first
#   fence     a (open_regex, close_regex, class) triple for the multi-line state
LANGS = {}


def _lang(key, **kw):
    kw.setdefault("names", ())
    kw.setdefault("shebang", None)
    kw.setdefault("block", None)
    kw.setdefault("indent", 4)
    kw.setdefault("tabs", False)
    kw.setdefault("fence", None)
    kw.setdefault("line", "")
    kw["key"] = key
    LANGS[key] = kw


_NUM = (r"\b(?:0[xX][0-9a-fA-F]+|0[bB][01]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b", "number")
_C_STR = (r'"(?:[^"\\\n]|\\.)*"', "string")
_S_STR = (r"'(?:[^'\\\n]|\\.)*'", "string")

_lang(
    "nix", name="nix", exts=(".nix",), line="#", indent=2,
    rules=[
        (r"#.*$", "comment"),
        (r"''(?:[^']|'(?!'))*''", "string"),
        _C_STR,
        (_kw("let in with rec inherit if then else assert import or "
             "builtins true false null"), "keyword"),
        (_kw("pkgs lib config stdenv mkDerivation fetchurl fetchgit "
             "mkIf mkMerge mkOption mkForce optionals optional"), "builtin"),
        (r"\$\{", "meta"),
        _NUM,
        (r"[=;:?@\[\]{}()|&!<>+*/-]", "punct"),
    ],
)

_lang(
    "python", name="python", exts=(".py", ".pyi"), names=("SConstruct",),
    shebang=r"python", line="#", indent=4,
    fence=(r'("""|\'\'\')', None, "string"),
    rules=[
        (r"#.*$", "comment"),
        (r'[frbu]{0,2}"(?:[^"\\\n]|\\.)*"', "string"),
        (r"[frbu]{0,2}'(?:[^'\\\n]|\\.)*'", "string"),
        (_kw("False None True and as assert async await break class continue "
             "def del elif else except finally for from global if import in is "
             "lambda nonlocal not or pass raise return try while with yield "
             "match case"), "keyword"),
        (_kw("abs all any bool bytes callable chr dict dir enumerate eval "
             "filter float format frozenset getattr hasattr hash hex id int "
             "isinstance issubclass iter len list map max min next object oct "
             "open ord pow print range repr reversed round set setattr sorted "
             "str sum super tuple type vars zip self cls"), "builtin"),
        (r"^\s*@[\w.]+", "meta"),
        _NUM,
        (r"[=:;,.<>+*/%&|^~!()\[\]{}-]", "punct"),
    ],
)

_JS_KW = ("break case catch class const continue debugger default delete do "
          "else export extends finally for function if import in instanceof "
          "let new return super switch this throw try typeof var void while "
          "with yield async await of static get set true false null undefined "
          "property readonly signal alias component required on enum pragma")

_lang(
    "qml", name="qml/js", exts=(".qml", ".js", ".mjs", ".ts"), line="//",
    block=("/*", "*/"), indent=4,
    fence=(r"/\*", r"\*/", "comment"),
    rules=[
        (r"//.*$", "comment"),
        (r"/\*.*?\*/", "comment"),
        _C_STR, _S_STR,
        (r"`(?:[^`\\]|\\.)*`", "string"),
        (_kw(_JS_KW), "keyword"),
        (_kw("Qt QtObject Item Rectangle Text TextEdit TextInput MouseArea "
             "Window Component Timer Repeater Column Row Grid Flickable "
             "ListModel ListView Connections Behavior NumberAnimation Math "
             "JSON console anchors parent"), "builtin"),
        (r"^\s*(?:id|import)\b", "meta"),
        _NUM,
        (r"[=:;,.<>+*/%&|^~!?()\[\]{}-]", "punct"),
    ],
)

_lang(
    "lua", name="lua", exts=(".lua",), line="--", block=("--[[", "]]"),
    indent=2,
    fence=(r"\[\[", r"\]\]", "string"),
    rules=[
        (r"--\[\[.*?\]\]", "comment"),
        (r"--.*$", "comment"),
        _C_STR, _S_STR,
        (_kw("and break do else elseif end false for function goto if in local "
             "nil not or repeat return then true until while"), "keyword"),
        (_kw("assert collectgarbage dofile error getmetatable ipairs load "
             "next pairs pcall print rawget rawset require select setmetatable "
             "tonumber tostring type xpcall self string table math os io"),
         "builtin"),
        _NUM,
        (r"[=:;,.<>+*/%#()\[\]{}-]", "punct"),
    ],
)

_lang(
    "cpp", name="c++", exts=(".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h", ".c",
                             ".inl"),
    line="//", block=("/*", "*/"), indent=4,
    fence=(r"/\*", r"\*/", "comment"),
    rules=[
        (r"//.*$", "comment"),
        (r"/\*.*?\*/", "comment"),
        _C_STR,
        (r"'(?:[^'\\\n]|\\.)'", "string"),
        (r"^\s*#\s*\w+", "meta"),
        (_kw("alignas alignof and asm auto bool break case catch char class "
             "co_await co_return co_yield concept const consteval constexpr "
             "const_cast continue decltype default delete do double "
             "dynamic_cast else enum explicit export extern false float for "
             "friend goto if inline int long mutable namespace new noexcept "
             "not nullptr operator or private protected public register "
             "reinterpret_cast requires return short signed sizeof static "
             "static_assert static_cast struct switch template this "
             "thread_local throw true try typedef typeid typename union "
             "unsigned using virtual void volatile while xor override final"),
         "keyword"),
        (_kw("size_t uint8_t uint16_t uint32_t uint64_t int8_t int16_t "
             "int32_t int64_t std string vector map set optional shared_ptr "
             "unique_ptr wl_display CBox Vector2D SP WP UP"), "type"),
        _NUM,
        (r"[=:;,.<>+*/%&|^~!?()\[\]{}-]", "punct"),
    ],
)

_lang(
    "sh", name="shell", exts=(".sh", ".bash", ".zsh", ".zshrc", ".bashrc"),
    names=(".zshrc", ".bashrc", ".profile", "PKGBUILD"),
    shebang=r"(?:ba|z|k|da)?sh", line="#", indent=2,
    rules=[
        (r"#.*$", "comment"),
        _C_STR, _S_STR,
        (_kw("if then elif else fi for while until do done case esac in "
             "function return break continue local export readonly declare "
             "typeset unset shift exit trap source eval exec set"), "keyword"),
        (_kw("echo printf read cd pwd test true false cat sed awk grep cut "
             "tr sort uniq head tail wc mkdir rm mv cp ln find xargs sudo "
             "systemctl hyprctl git nix"), "builtin"),
        (r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\$[0-9@*#?!$]", "meta"),
        _NUM,
        (r"[=;|&<>()\[\]{}]", "punct"),
    ],
)

_lang(
    "json", name="json", exts=(".json", ".jsonc", ".lock", ".webmanifest"),
    names=("flake.lock",), line="", indent=2,
    rules=[
        (r'"(?:[^"\\]|\\.)*"\s*:', "keyword"),      # a key is not a string
        _C_STR,
        (_kw("true false null"), "builtin"),
        _NUM,
        (r"[{}\[\],:]", "punct"),
    ],
)

_lang(
    "md", name="markdown", exts=(".md", ".markdown", ".mdown"),
    line="", block=("<!--", "-->"), indent=2,
    fence=(r"^\s*(?:```|~~~)", r"^\s*(?:```|~~~)", "string"),
    rules=[
        (r"^\s{0,3}#{1,6}\s.*$", "heading"),
        (r"^\s*>.*$", "comment"),
        (r"`[^`]+`", "string"),
        (r"\*\*[^*]+\*\*|__[^_]+__", "emph"),
        (r"\[[^\]]*\]\([^)]*\)", "meta"),
        (r"^\s*(?:[-*+]|\d+\.)\s", "keyword"),
        (r"^\s*(?:---+|===+|\*\*\*+)\s*$", "punct"),
        (r"\|", "punct"),
    ],
)

_lang(
    "conf", name="conf", exts=(".conf", ".ini", ".cfg", ".toml", ".desktop",
                               ".service", ".rules", ".yaml", ".yml"),
    line="#", indent=2,
    rules=[
        (r"[#;].*$", "comment"),
        (r"^\s*\[[^\]]*\]", "heading"),
        _C_STR, _S_STR,
        (r"^\s*[\w.-]+(?=\s*[:=])", "keyword"),
        (_kw("true false yes no on off none"), "builtin"),
        _NUM,
        (r"[=:,]", "punct"),
    ],
)

_lang("text", name="text", exts=(".txt", ".log"), line="", indent=4, rules=[])


def compile_rules():
    """Compile every language's rules once, in place. Called at import: a
    per-keystroke `re.compile` in `highlightBlock` is the classic way a
    highlighter becomes the reason typing feels heavy."""
    for lg in LANGS.values():
        lg["crules"] = [(re.compile(pat, re.MULTILINE), cls)
                        for pat, cls in lg["rules"]]
        f = lg.get("fence")
        if f:
            lg["cfence"] = (re.compile(f[0]), re.compile(f[1]) if f[1] else None,
                            f[2])
        else:
            lg["cfence"] = None


compile_rules()

_BY_EXT = {}
_BY_NAME = {}
for _k, _lg in LANGS.items():
    for _e in _lg["exts"]:
        _BY_EXT.setdefault(_e, _k)
    for _n in _lg["names"]:
        _BY_NAME.setdefault(_n, _k)


def detect(path, first_line=""):
    """The language for a file: exact basename, then extension, then `#!`.

    Order matters — `flake.lock` is json by name and would be nothing by
    extension, and a `.sh`-less shell script is only knowable from its shebang.
    Falls back to `text`, which highlights nothing and is never wrong."""
    import os
    base = os.path.basename(path or "")
    if base in _BY_NAME:
        return _BY_NAME[base]
    ext = os.path.splitext(base)[1].lower()
    if ext in _BY_EXT:
        return _BY_EXT[ext]
    fl = (first_line or "").strip()
    if fl.startswith("#!"):
        for key, lg in LANGS.items():
            if lg["shebang"] and re.search(lg["shebang"], fl):
                return key
    return "text"


class Highlighter(QSyntaxHighlighter):
    """One per open document. Paints syntax AND the find bar's all-matches
    highlight in a single pass over each block.

    Colours are pulled from the `Palette` object on every `refresh()` rather
    than captured at construction, so a wallpaper change recolours open
    documents in lock-step with the panel and the titlebars (docs/DESIGN.md
    §3.1) — the same live-repaint every other app here gets for free by
    binding, which a QSyntaxHighlighter cannot do because it is not QML."""

    def __init__(self, doc, palette, lang="text"):
        super().__init__(doc)
        self._palette = palette
        self._lang = lang if lang in LANGS else "text"
        self._fmt = {}
        self._query_re = None
        self._match_fmt = QTextCharFormat()
        self.refresh()

    # ---- configuration ----

    def language(self):
        return self._lang

    def set_language(self, lang):
        lang = lang if lang in LANGS else "text"
        if lang == self._lang:
            return
        self._lang = lang
        self.rehighlight()

    def set_query(self, pattern, regex=False, case=False):
        """The find bar's query, as a compiled matcher — or None to unlight.

        An invalid regex unlights rather than raising: the user is halfway
        through typing `(foo` most of the time they see this, and a find bar
        that throws on every second keystroke is worse than one that lights
        nothing yet. The bar reports validity separately (main.py `findValid`),
        so this is not a silent failure — docs/DESIGN.md §10.2."""
        old = self._query_re.pattern if self._query_re else None
        if not pattern:
            self._query_re = None
        else:
            flags = 0 if case else re.IGNORECASE
            try:
                self._query_re = re.compile(pattern if regex
                                            else re.escape(pattern), flags)
            except re.error:
                self._query_re = None
        new = self._query_re.pattern if self._query_re else None
        if new != old:
            self.rehighlight()

    def refresh(self):
        """(Re)resolve every token class against the live palette."""
        p = self._palette
        self._fmt = {}
        for cls, slot in ROLE.items():
            f = QTextCharFormat()
            f.setForeground(QColor(p.color(slot)))
            self._fmt[cls] = f
        m = QTextCharFormat()
        m.setBackground(QColor(p.color("highlight")))
        m.setForeground(QColor(p.color("accent")))
        self._match_fmt = m
        self.rehighlight()

    # ---- the pass ----

    def highlightBlock(self, text):
        lg = LANGS[self._lang]
        fence = lg["cfence"]

        # 1. the multi-line construct, if this language has one. State 1 means
        #    "this block began inside it". Everything inside is one class and no
        #    other rule may claim any of it, which is what makes a `#` inside a
        #    Python docstring stay a docstring.
        pos = 0
        in_fence = self.previousBlockState() == 1
        self.setCurrentBlockState(0)
        if fence:
            open_re, close_re, cls = fence
            fmt = self._fmt.get(cls, self._fmt["comment"])
            if close_re is None:
                # a symmetric delimiter (Python/Lua triple quote): count them
                marks = list(open_re.finditer(text))
                if in_fence:
                    if marks:
                        self.setFormat(0, marks[0].end(), fmt)
                        pos = marks[0].end()
                        if len(marks) % 2 == 0:
                            self.setCurrentBlockState(1)
                    else:
                        self.setFormat(0, len(text), fmt)
                        self.setCurrentBlockState(1)
                        self._light_matches(text)
                        return
                elif marks:
                    start = marks[0].start()
                    if len(marks) >= 2:
                        # Opened AND closed on this line. The rules run on the
                        # two ends only — running them over the whole line would
                        # let the comment rule repaint a `#` that is inside the
                        # string, which is exactly the bug this branch exists to
                        # avoid.
                        self.setFormat(start, marks[-1].end() - start, fmt)
                        self._rules(text, 0, start)
                        self._rules(text, marks[-1].end(), len(text))
                        self._light_matches(text)
                        return
                    else:
                        self.setFormat(start, len(text) - start, fmt)
                        self.setCurrentBlockState(1)
                        self._rules(text, 0, start)
                        self._light_matches(text)
                        return
            else:
                if in_fence:
                    m = close_re.search(text)
                    if not m:
                        self.setFormat(0, len(text), fmt)
                        self.setCurrentBlockState(1)
                        self._light_matches(text)
                        return
                    self.setFormat(0, m.end(), fmt)
                    pos = m.end()
                else:
                    m = open_re.search(text)
                    if m and not close_re.search(text, m.end()):
                        self.setFormat(m.start(), len(text) - m.start(), fmt)
                        self.setCurrentBlockState(1)
                        self._rules(text, 0, m.start())
                        self._light_matches(text)
                        return

        # 2. the ordinary rules, first-claim-wins
        self._rules(text, pos, len(text))
        # 3. the find bar's highlight, over the top
        self._light_matches(text)

    def _rules(self, text, lo, hi):
        if hi <= lo:
            return
        claimed = bytearray(hi - lo)
        for rx, cls in LANGS[self._lang]["crules"]:
            fmt = self._fmt.get(cls)
            if fmt is None:
                continue
            for m in rx.finditer(text, lo, hi):
                s, e = m.start(), m.end()
                if e <= s or any(claimed[s - lo:e - lo]):
                    continue
                self.setFormat(s, e - s, fmt)
                claimed[s - lo:e - lo] = b"\x01" * (e - s)

    def _light_matches(self, text):
        if self._query_re is None:
            return
        for m in self._query_re.finditer(text):
            if m.end() > m.start():
                self.setFormat(m.start(), m.end() - m.start(), self._match_fmt)
