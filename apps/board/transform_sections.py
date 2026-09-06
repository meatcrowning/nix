#!/usr/bin/env python3
"""One-off structural transform for the board's section reorder (2026-08-01).

Turns the four hardcoded top-level sections in qml/Main.qml (needs / summoner /
the triangle / landed) into order-driven Repeater delegates, so dragging their
bands can reorder them. Reads the REAL file so the ~1100 lines of section body
are preserved byte-for-byte (only re-indented by one level), nothing else in the
file is touched. Kept as a separate throwaway script because the patch tool
cannot express a multi-hundred-line relocation.
"""
import re
import sys

p = "apps/board/qml/Main.qml"
src = open(p, encoding="utf-8").read()
lines = src.split("\n")

# --- anchors ---------------------------------------------------------------
start = None
for i, l in enumerate(lines):
    if l.lstrip().startswith("// ===") and "what needs you" in l:
        start = i
        break
assert start is not None, "needs-section comment not found"

# The region ends where the `Board.path` footer PixelText begins — the footer's
# opening is a 12-space-indented `PixelText {`; scan back to it so the whole
# footer block survives intact below the Repeater.
tp = None
for i, l in enumerate(lines):
    if "text: Board.path" in l:
        tp = i
        break
assert tp is not None, "Board.path footer text not found"
end = None
for i in range(tp, -1, -1):
    if lines[i].rstrip() == "            PixelText {":
        end = i
        break
assert end is not None, "board-path PixelText opening not found"

region = lines[start:end]

# Split into the four section blocks by the top-level vertical spacers that sit
# between (and after) them. A top-level spacer is a 12-space-indented
# `Item { width: 1; height: N }` line — the bodies' own spacers are deeper.
spacer_re = re.compile(r"^ {12}Item \{ width: 1; height: \d+ \}$")
bounds = [0]
for i, l in enumerate(region):
    if spacer_re.match(l):
        bounds.append(i)
bounds.append(len(region))

# bounds should yield 4 blocks and 4 separators: needs,summoner,agents,landed.
# region[0 .. b1] needs, spacer, [..b2] summoner, spacer, [..b3] agents, spacer,
# [..b4] landed, spacer. That is blocks at [0,b1],[b1+1,b2],
assert len(bounds) == 6, f"expected 4 spacers, got bounds={bounds}"
blocks = []
seps = []
for k in range(4):
    b0 = bounds[k] + (1 if k > 0 else 0)   # skip the separator we consumed
    b1 = bounds[k + 1]                     # up to next spacer
    blocks.append(region[b0:b1])
    seps.append(region[bounds[k + 1]])

def reindent(blk, shift=4):
    return [(" " * shift + l) if l.strip() else "" for l in blk]

KEY = ["needs", "summoner", "agents", "landed"]
comps = []
for k, name in enumerate(KEY):
    body = reindent(blocks[k] + [seps[k]])
    comps.append(
        "Component {\n"
        f"    id: {name}Section\n"
        "    //: the section as a delegate of the page's `sectionsCol` Repeater,\n"
        "    //  so dragging its band reorders it ([his answer, 2026-08-01]: the\n"
        "    //  four top-level sections move, persisted apart from board.md). The\n"
        "    //  root is a Column so it sizes to its children exactly as the old\n"
        "    //  page Column did — a section's collapse, growth or shrinkage re-flows\n"
        "    //  the ones below it.\n"
        "    Column {\n"
        "        width: page.width\n"
        + "\n".join(body) + "\n"
        "    }\n"
        "}\n")

# The Repeater that replaces the old hardcoded region.
region_new = (
    "            // ========================================== the four sections\n"
    "            // [his ask, 2026-08-01] needs / summoner / the triangle / landed\n"
    "            // are drawn in `win.sectionOrder`: drag one of their bands to move\n"
    "            // it, and the new display order persists to Settings, not board.md\n"
    "            // (summoner and the triangle are the machine, not the store —\n"
    "            // guide/drawing.md). Keyed on the order array so a drop just\n"
    "            // changes the model and the Column re-lays everything (§6.1's\n"
    "            // diff trick — an equal list is not a change, so a no-op reload\n"
    "            // touches nothing).\n"
    "            Column {\n"
    "                id: sectionsCol\n"
    "                width: page.width\n"
    "                Repeater {\n"
    "                    id: sectionsRepeater\n"
    "                    model: win.sectionOrder\n"
    "                    delegate: Loader {\n"
    "                        readonly property string sectionKey: String(modelData)\n"
    "                        width: sectionsCol.width\n"
    "                        // Size to the loaded section so the Column lays the\n"
    "                        // sections out by their real heights (§6.1); when one\n"
    "                        // collapses or grows the re-flow follows.\n"
    "                        height: item ? item.height : 0\n"
    "                        sourceComponent: {\n"
    "                            switch (String(modelData)) {\n"
    "                            case \"needs\": return needsSection\n"
    "                            case \"summoner\": return summonerSection\n"
    "                            case \"agents\": return agentsSection\n"
    "                            case \"landed\": return landedSection\n"
    "                            }\n"
    "                            return null\n"
    "                        }\n"
    "                    }\n"
    "                }\n"
    "            }\n").split("\n")

out = lines[:start] + region_new + lines[end:]

# Preserve the comment lines that sat between the last section and the footer
# PixelText (region's trailing tail after the final spacer) — they explain the
# footer, and dropping them would silently edit his documentation.
tail = region[bounds[-2] + 1:]
out = lines[:start] + region_new + tail + lines[end:]

# Insert the four component definitions just before the store-error overlay
# (after the page Column has closed).
anchor = "    // An unreadable store says so instead of drawing an empty board"
ai = next(i for i, l in enumerate(out) if l.startswith(anchor))
components_block = [""] + comps
out = out[:ai] + components_block + out[ai:]

open(p, "w", encoding="utf-8").write("\n".join(out))
print("transformed OK")
print(f"components: {len(comps)}")
print("done")
