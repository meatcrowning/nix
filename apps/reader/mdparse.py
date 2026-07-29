"""reader's markdown parser: text on disk -> a flat list of BLOCKS to draw.

WHY THERE IS A PARSER HERE AT ALL, rather than `Text.MarkdownText`. Qt renders
markdown for free, and it was rejected on four counts, each of which is a rule
in ~/nix/docs/DESIGN.md rather than a preference:

  * `Text.MarkdownText` is not `Text.PlainText` (§2.6). Qt's markdown reader
    also accepts embedded HTML, so a document downloaded from anywhere could
    style this app's chrome or pull a remote `<img>` as a read beacon. Every
    label on this desktop is PlainText for exactly that reason, and a program
    whose whole job is rendering files other people wrote is the last place to
    make an exception.
  * It draws headings BOLD and LARGER. More Perfect DOS VGA ships Regular only,
    so Qt would synthesize a smeared fake bold (§2.2), and the sizes would be
    multiples of a font size that is a desktop-wide setting (§2.1, §2.7) — i.e.
    text on this desktop at a size nothing else on this desktop uses.
  * `lineHeight`/`lineHeightMode` (kitty-exact packing, §2.1) apply to the whole
    item, so a document of mixed leading cannot be packed like a terminal.
  * Links, code fences and headings are then unreachable: no click target to
    hang document history on (§11.1), no block to copy, no headings to build an
    outline from, and no way to highlight a search hit.

So the trade is: this file, and a run/line layout in QML, against inline images
and bold. Both of those are losses this desktop has already accepted.

BLOCKS. Each is a plain dict (a QVariantMap on the QML side):

    {type: "h",     level, runs, text, anchor}
    {type: "p",     runs, text}
    {type: "li",    runs, text, depth, marker}
    {type: "quote", runs, text, depth}
    {type: "code",  lines, lang, text}
    {type: "table", rows: [[cellRuns...]...], head: bool, text}
    {type: "hr"}

RUNS are the inline layer: `[{t, k, href, lt}]`, `k` in `"" | "code" | "link"`.
Emphasis markers are STRIPPED and carry no styling — §2.2's "bold emphasis is a
deliberately accepted loss", stated for the whole desktop.

Every piece of drawable text is mapped through `pylib/glyphs.px()` HERE, at
ingest, which is what §2.3 asks for. `text` (the block's plain form) is mapped
too, because it is what gets copied to the clipboard and searched — the search
box is typed in this font, so it must match what the reader can see. `href` is
NEVER mapped: it is a path or a URL that gets opened.
"""
import os
import re

from glyphs import px

# Extensions reader treats as "a document it can open" — used both for link
# resolution and for the file index.
DOC_EXTS = {".md", ".markdown", ".mdown", ".mkd", ".mkdn", ".mdwn", ".text"}

_FENCE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})\s*([^`\s]*)")
_HEADING = re.compile(r"^(\s{0,3})(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s{0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$")
_BULLET = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
_QUOTE = re.compile(r"^(\s{0,3})((?:>\s?)+)(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")

# Inline: a code span, a link, or an autolink. Everything else is plain text.
_INLINE = re.compile(
    r"(?P<code>`+)(?P<codetext>.+?)(?P=code)"
    r"|\[(?P<ltext>[^\]]*)\]\((?P<ldest>[^)\s]*)(?:\s+\"[^\"]*\")?\)"
    r"|<(?P<auto>(?:https?|ftp|mailto):[^>\s]+)>",
    re.S,
)

# Emphasis markers, stripped once the code spans and links are out of the way.
# `*` is only treated as a marker when it hugs non-space on the inside and a
# non-word character on the outside, so `*.nix` and `a * b` survive intact —
# this repo's own docs are full of both.
_EM = [
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S), r"\1"),
    (re.compile(r"__(?=\S)(.+?)(?<=\S)__", re.S), r"\1"),
    (re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S), r"\1"),
    (re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", re.S), r"\1"),
    (re.compile(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", re.S), r"\1"),
]

_SLUG_DROP = re.compile(r"[^\w\s-]")


def slug(text):
    """GitHub's heading anchor form: lowercase, punctuation dropped, spaces to
    hyphens. Matches how `docs/DESIGN.md`'s own contents table links to its sections,
    which is the corpus this app was written for."""
    s = _SLUG_DROP.sub("", text.lower()).strip()
    return re.sub(r"\s+", "-", s)


def _strip_em(s):
    for rx, rep in _EM:
        s = rx.sub(rep, s)
    return s.replace("\\*", "*").replace("\\_", "_").replace("\\`", "`")


def _resolve(dest, base_dir):
    """(link type, href) for a link destination, or None if it points nowhere.

    Returning None is the honest-affordance rule (§10) applied at ingest: a link
    whose target does not exist is drawn as ORDINARY TEXT, not as a control that
    does nothing when clicked. That decision is cheap here and impossible later.
    """
    if not dest:
        return None
    if dest.startswith("#"):
        return ("anchor", dest[1:].lower())
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", dest):
        return ("url", dest)
    path, _, frag = dest.partition("#")
    if not path:
        return None
    p = os.path.normpath(os.path.join(base_dir, path))
    if not os.path.exists(p):
        return None
    if os.path.isdir(p):
        return None
    kind = "doc" if os.path.splitext(p)[1].lower() in DOC_EXTS else "file"
    return (kind, p + ("#" + frag.lower() if frag else ""))


def runs_of(src, base_dir):
    """Inline markdown -> a list of runs. See the module docstring."""
    out = []

    def plain(s):
        if not s:
            return
        s = px(_strip_em(s))
        if s:
            out.append({"t": s, "k": "", "href": "", "lt": ""})

    pos = 0
    for m in _INLINE.finditer(src):
        plain(src[pos:m.start()])
        pos = m.end()
        if m.group("code") is not None:
            # A code span is verbatim by definition, but it is still DRAWN in
            # this font, so it is mapped like everything else. Nothing is run
            # from it.
            out.append({"t": px(m.group("codetext").strip()), "k": "code",
                        "href": "", "lt": ""})
            continue
        if m.group("auto") is not None:
            url = m.group("auto")
            out.append({"t": px(url), "k": "link", "href": url, "lt": "url"})
            continue
        got = _resolve(m.group("ldest"), base_dir)
        label = m.group("ltext") or m.group("ldest")
        if got is None:
            plain(label)
        else:
            # href is the RAW resolved target: never px()-mapped, because it is
            # opened, not drawn.
            out.append({"t": px(_strip_em(label)), "k": "link",
                        "href": got[1], "lt": got[0]})
    plain(src[pos:])
    if not out:
        out.append({"t": "", "k": "", "href": "", "lt": ""})
    return out


def _text_of(runs):
    return "".join(r["t"] for r in runs)


def _split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def parse(text, base_dir=""):
    """The whole document, as blocks. `base_dir` is the document's own directory
    — link targets are resolved against it, once, here."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    para = []          # pending paragraph lines
    seen_anchors = {}

    def flush_para():
        if not para:
            return
        src = " ".join(l.strip() for l in para)
        para.clear()
        r = runs_of(src, base_dir)
        blocks.append({"type": "p", "runs": r, "text": _text_of(r)})

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]

        fence = _FENCE.match(line)
        if fence:
            flush_para()
            mark, lang = fence.group(2), fence.group(3)
            body, i = [], i + 1
            while i < n:
                closing = _FENCE.match(lines[i])
                if closing and closing.group(2)[0] == mark[0] and len(closing.group(2)) >= len(mark):
                    i += 1
                    break
                body.append(lines[i])
                i += 1
            # A code fence keeps its lines verbatim (tabs expanded, since this
            # renderer has no tab stops), still mapped for the font.
            body = [px(b.replace("\t", "    ")) for b in body]
            blocks.append({"type": "code", "lines": body, "lang": px(lang),
                           "text": "\n".join(body)})
            continue

        if not line.strip():
            flush_para()
            i += 1
            continue

        # An HTML COMMENT is drawn by nothing, which is what makes it the way to
        # put a machine-readable fact into a document a human reads. It was
        # rendered here as an ordinary paragraph until `docs/board.md` grew one:
        # `boardparse`'s `<!-- answered-on: <host> -->` stamp, which says which
        # machine an answer was typed on so that board-watch running on BOTH
        # machines cannot work it twice. Skipped as a BLOCK, since a comment may
        # span lines; an unterminated one is skipped to the end of the file,
        # which is what every markdown renderer does with it.
        if line.lstrip().startswith("<!--"):
            flush_para()
            while i < n and "-->" not in lines[i]:
                i += 1
            i += 1
            continue

        head = _HEADING.match(line)
        if head:
            flush_para()
            r = runs_of(head.group(3), base_dir)
            txt = _text_of(r)
            a = slug(txt)
            # Duplicate headings get GitHub's -1/-2 suffix, so an anchor link
            # into a document with two "## Notes" reaches the right one.
            if a in seen_anchors:
                seen_anchors[a] += 1
                a = "%s-%d" % (a, seen_anchors[a])
            else:
                seen_anchors[a] = 0
            blocks.append({"type": "h", "level": len(head.group(2)), "runs": r,
                           "text": txt, "anchor": a})
            i += 1
            continue

        if _HR.match(line):
            flush_para()
            blocks.append({"type": "hr", "text": ""})
            i += 1
            continue

        quote = _QUOTE.match(line)
        if quote:
            flush_para()
            depth = quote.group(2).count(">")
            body = [quote.group(3)]
            i += 1
            while i < n:
                q2 = _QUOTE.match(lines[i])
                if q2 and q2.group(2).count(">") == depth:
                    body.append(q2.group(3))
                    i += 1
                elif lines[i].strip() and not _QUOTE.match(lines[i]) and body and body[-1].strip():
                    body.append(lines[i].strip())   # lazy continuation
                    i += 1
                else:
                    break
            r = runs_of(" ".join(b.strip() for b in body), base_dir)
            blocks.append({"type": "quote", "runs": r, "text": _text_of(r),
                           "depth": depth})
            continue

        bullet = _BULLET.match(line)
        ordered = None if bullet else _ORDERED.match(line)
        if bullet or ordered:
            flush_para()
            m = bullet or ordered
            indent = len(m.group(1).replace("\t", "    "))
            marker = "-" if bullet else (m.group(2) + ".")
            body = [m.group(3)]
            i += 1
            # Continuation lines of the same item: indented further, and not
            # themselves a marker or a fence.
            while i < n and lines[i].strip():
                nxt = lines[i]
                if _BULLET.match(nxt) or _ORDERED.match(nxt) or _FENCE.match(nxt) \
                   or _HEADING.match(nxt) or _QUOTE.match(nxt):
                    break
                if len(nxt) - len(nxt.lstrip()) <= indent:
                    break
                body.append(nxt.strip())
                i += 1
            r = runs_of(" ".join(body), base_dir)
            blocks.append({"type": "li", "runs": r, "text": _text_of(r),
                           "depth": min(4, indent // 2), "marker": marker})
            continue

        # A table is a row of `|` cells whose NEXT line is the `---|---` rule.
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            flush_para()
            head_cells = _split_row(line)
            rows = [[runs_of(c, base_dir) for c in head_cells]]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append([runs_of(c, base_dir) for c in _split_row(lines[i])])
                i += 1
            flat = "\n".join("  ".join(_text_of(c) for c in row) for row in rows)
            blocks.append({"type": "table", "rows": rows, "head": True,
                           "text": flat})
            continue

        para.append(line)
        i += 1

    flush_para()
    return blocks


def outline(blocks):
    """[{index, level, text, anchor}] for every heading — the outline pane's
    model, and what an in-document `#anchor` link resolves against."""
    return [{"index": i, "level": b["level"], "text": b["text"],
             "anchor": b["anchor"]}
            for i, b in enumerate(blocks) if b["type"] == "h"]
