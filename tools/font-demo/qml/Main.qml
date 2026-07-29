// font-demo - a three-way specimen sheet for the pixel-font decision.
//
// Same content in three columns, one per candidate, so they can be read against
// each other. Chrome (headings, notes, size labels) is drawn in the CURRENT face
// and is ASCII-only on purpose: all three render ASCII identically, so the
// furniture cannot flatter one column over another. Only the specimen text is in
// that column's own family.
//
// docs/DESIGN.md: black bg, live wal palette, square corners, no bold,
// NativeRendering + PreferFullHinting + antialiasing off, pixel sizes, rows one
// font cell tall. The clipped rows in section 5 are not a bug in this window -
// they are the CURRENT font's missing-glyph failure (S2.3) reproduced at the
// desktop's real row geometry, which is the thing being chosen about.
//
// Nested Repeaters here bind through the outer delegate's `id`, never through a
// second `required property var modelData` - the inner one shadows the outer and
// silently leaves font.family empty.

import QtQuick

Window {
    id: root
    visible: true
    width: 1880
    height: 1000
    minimumWidth: 1100
    minimumHeight: 600
    title: "font-demo - pixel font candidates"
    color: Wal.bg

    readonly property int gutter: 10
    readonly property int colWidth: Math.floor((width - gutter * 4) / 3)

    // ---- the three candidates -------------------------------------------
    readonly property var options: [
        {
            family: Fonts.current,
            name: "1. CURRENT",
            sub: "More Perfect DOS VGA as shipped - 255 codepoints",
            gain: "+ Nothing changes at all. No risk, no work, no new file.",
            cost: "- 88 wanted codepoints missing, 43 of them ordinary Latin-1\n"
                + "  accented capitals. Each falls back to a proportional font\n"
                + "  for that one character, takes its taller ascent, and clips\n"
                + "  the whole row. Glyphs.px() has to keep rewriting text to\n"
                + "  ASCII at every ingest point, forever."
        },
        {
            family: Fonts.merged,
            name: "2. MERGED, with the real ellipsis",
            sub: "+ 526 codepoints from PxPlus IBM VGA 9x16 - 781 total",
            gain: "+ Everything on this sheet draws in the pixel font. Printable\n"
                + "  ASCII measured pixel-identical to CURRENT at 10/12/15/17/\n"
                + "  20/24 px - literally 0 differing pixels.",
            cost: "- Having U+2026, Qt stops substituting three periods, so about\n"
                + "  45 Text.elide sites switch to a one-cell ellipsis. Elided\n"
                + "  text you already have gets visibly shorter. See section 6:\n"
                + "  that is the ONLY visible change to existing text."
        },
        {
            family: Fonts.noell,
            name: "3. MERGED, without the ellipsis",
            sub: "the same font with U+2026 removed - 780 total",
            gain: "+ Identical to option 2 everywhere except elision, and elision\n"
                + "  still renders '...' exactly as today. Text you already have\n"
                + "  is LITERALLY unchanged - only new glyphs appear.",
            cost: "- The font lacks one glyph it could have had, so an ellipsis\n"
                + "  pasted in from outside text stays a fallback character and\n"
                + "  still clips its row."
        }
    ]

    // ---- text primitives, the desktop's (docs/DESIGN.md S2.2) -----------
    component PixelText: Text {
        property int px: 15
        textFormat: Text.PlainText
        font.pixelSize: px
        font.hintingPreference: Font.PreferFullHinting
        renderType: Text.NativeRendering
        antialiasing: false
        lineHeight: px
        lineHeightMode: Text.FixedHeight
        color: Wal.text
    }

    component Chrome: PixelText {
        font.family: Fonts.current   // ASCII only - identical in all three
        color: Wal.textDim
    }

    component SectionHead: Item {
        property string label: ""
        property string note: ""
        width: root.width - root.gutter * 2
        height: 46
        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 1
            color: Wal.border
        }
        Chrome { y: 8; px: 15; color: Wal.accent; text: parent.label }
        Chrome { y: 24; px: 15; text: parent.note }
    }

    component Card: Rectangle {
        color: Wal.bgAlt
        border.width: 1
        border.color: Wal.border
        width: root.colWidth
    }

    // ---- specimen content ------------------------------------------------
    readonly property string pangram: "Sphinx of black quartz, judge my vow 0123456789"
    readonly property var sizes: [10, 12, 15, 17, 20, 24]

    readonly property string prose:
          "The quick brown fox jumps over the lazy dog\n"
        + "while twelve wizards make toxic brew for the\n"
        + "evil Queen and Jack. Pack my box with five\n"
        + "dozen liquor jugs. ABCDEFGHIJKLMNOPQRSTUVWXYZ\n"
        + "abcdefghijklmnopqrstuvwxyz 0123456789\n"
        + "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"

    readonly property string accents:
          "A A A A A A AE C E E E E\n"
        + "À Á Â Ã Ä Å Æ Ç È É Ê Ë\n"
        + "Ì Í Î Ï Ð Ñ Ò Ó Ô Õ Ö Ø\n"
        + "Ù Ú Û Ü Ý Þ Œ Š Ÿ Ž ß Æ\n"
        + "à é î õ ü ç ñ ø å æ œ š"

    readonly property string symbols:
          "…  −  ↑ ↓ ← → ↔  ▲ ▼ ▶ ◀\n"
        + "● • ♫ § ¶ ™ © ® × ÷ ≠\n"
        + "✓ ✗ ★ ☆ ⚠ ↩ ⇒ ⇐ ≫ ‖"

    readonly property string boxes:
          "┌─┬─┐   ╔═╦═╗   ░▒▓█\n"
        + "├─┼─┤   ╠═╬═╣   █▓▒░\n"
        + "└─┴─┘   ╚═╩═╝   ▖▗▘▝"

    readonly property string punct:
          "— – - −    ‘quoted’  “quoted”\n"
        + "« guillemets »  ‹ ›   ¡ ¿\n"
        + "† ‡ ‰ ° ± ¼ ½ ¾ ² ³ µ"

    // His own desktop's strings, not lorem ipsum.
    readonly property var realRows: [
        "CPU 12%  MEM 7.4G  BAT 100%  21:45",
        "Documents/Projects - 47 items, 3.2 GB",
        "03  Aphex Twin - Xtal [Ambient 85-92]  4:52"
    ]

    // The same kind of rows carrying characters the current font lacks.
    readonly property var realRowsHard: [
        "CPU 12% ↑  MEM 7.4G  ±0.3G  21:45",
        "Musique/Années 80 — Édith Piaf … 47 items",
        "07  Björk - Jóga [Homogenic] ♫ 4:52 ▶"
    ]

    readonly property var elideRows: [
        "Documents/Projects/generation-engine/output/2026-07-28/batch-0042-final.png",
        "03  Aphex Twin - Xtal [Selected Ambient Works 85-92]  4:52",
        "CPU 12%  MEM 7.4G  BAT 100%  NET 1.2M/s  DISK 84%  21:45"
    ]

    // ---- layout ----------------------------------------------------------
    // Flickable, not ScrollView: QtQuick.Controls resolves to the Breeze style
    // in this session's environment, which needs Kirigami and fails to load.
    // A plain Flickable scrolls on the wheel and pulls in no style at all.
    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: sheet.implicitHeight + 20
        boundsBehavior: Flickable.StopAtBounds
        clip: true

        Column {
            id: sheet
            x: root.gutter
            width: root.width - root.gutter * 2
            spacing: 0

            Item { width: 1; height: 8 }
            Chrome { px: 20; color: Wal.accent; text: "PIXEL FONT - THREE CANDIDATES" }
            Item { width: 1; height: 6 }
            Chrome {
                text: "Demo only. All three faces are loaded privately into this window - nothing is installed, "
                      + "fontconfig and the desktop's live font are untouched. Close it and the machine is as it was."
            }
            Chrome {
                text: "Same content in every column. Where a column shows the wrong typeface or a clipped row, "
                      + "that is the honest result for that option, not a bug in this window."
            }
            Item { width: 1; height: 10 }

            // ---------- column headers + the trade ----------
            Row {
                spacing: root.gutter
                Repeater {
                    model: root.options
                    delegate: Card {
                        id: hdrCard
                        required property var modelData
                        height: hdrCol.implicitHeight + 12
                        Column {
                            id: hdrCol
                            x: 6; y: 6
                            width: parent.width - 12
                            spacing: 0
                            Chrome { px: 17; color: Wal.accent; text: hdrCard.modelData.name }
                            Chrome { px: 15; text: hdrCard.modelData.sub }
                            Item { width: 1; height: 8 }
                            Chrome { px: 15; color: Wal.ok; text: hdrCard.modelData.gain }
                            Item { width: 1; height: 6 }
                            Chrome { px: 15; color: Wal.warn; text: hdrCard.modelData.cost }
                        }
                    }
                }
            }

            // ---------- 1. size ladder ----------
            SectionHead {
                label: "1. SIZE LADDER"
                note: "the font-size setting's whole range - 10 / 12 / 15 / 17 / 20 / 24 px. 15 is the default (kitty's cell)."
            }
            Row {
                spacing: root.gutter
                Repeater {
                    model: root.options
                    delegate: Card {
                        id: ladderCard
                        required property var modelData
                        height: ladder.implicitHeight + 12
                        Column {
                            id: ladder
                            x: 6; y: 6
                            spacing: 5
                            Repeater {
                                model: root.sizes
                                delegate: Row {
                                    id: ladderRow
                                    required property int modelData
                                    spacing: 6
                                    Chrome {
                                        px: 15
                                        width: 32
                                        horizontalAlignment: Text.AlignRight
                                        text: ladderRow.modelData + "px"
                                    }
                                    PixelText {
                                        px: ladderRow.modelData
                                        font.family: ladderCard.modelData.family
                                        text: root.pangram
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ---------- 2. prose ----------
            SectionHead {
                label: "2. MIXED-CASE PROSE AND FULL ASCII, at 15px"
                note: "rows one font cell tall with zero inter-row gap, exactly as the desktop draws them"
            }
            Row {
                spacing: root.gutter
                Repeater {
                    model: root.options
                    delegate: Card {
                        id: proseCard
                        required property var modelData
                        height: proseText.implicitHeight + 12
                        PixelText {
                            id: proseText
                            x: 6; y: 6
                            font.family: proseCard.modelData.family
                            text: root.prose
                        }
                    }
                }
            }

            // ---------- 3. accented capitals ----------
            SectionHead {
                label: "3. LATIN-1 ACCENTED CAPITALS - 43 of these are missing today"
                note: "the biggest single gap, and it is ordinary European text, not decoration. First line is the ASCII the desktop currently substitutes."
            }
            Row {
                spacing: root.gutter
                Repeater {
                    model: root.options
                    delegate: Card {
                        id: accCard
                        required property var modelData
                        height: accText.implicitHeight + 12
                        PixelText {
                            id: accText
                            x: 6; y: 6
                            px: 17
                            font.family: accCard.modelData.family
                            text: root.accents
                        }
                    }
                }
            }

            // ---------- 4. symbols, arrows, boxes, punctuation ----------
            SectionHead {
                label: "4. SYMBOLS, ARROWS, BOX DRAWING, DASHES AND QUOTES"
                note: "every character Glyphs.px() currently has to rewrite to ASCII before anything on this desktop can draw it"
            }
            Row {
                spacing: root.gutter
                Repeater {
                    model: root.options
                    delegate: Card {
                        id: symCard
                        required property var modelData
                        height: symCol.implicitHeight + 12
                        Column {
                            id: symCol
                            x: 6; y: 6
                            spacing: 9
                            PixelText { px: 17; font.family: symCard.modelData.family; text: root.symbols }
                            PixelText { px: 17; font.family: symCard.modelData.family; text: root.boxes }
                            PixelText { px: 15; font.family: symCard.modelData.family; text: root.punct }
                        }
                    }
                }
            }

            // ---------- 5. real rows at real row geometry ----------
            SectionHead {
                label: "5. REAL DESKTOP ROWS - plain ASCII above the rule, the same rows carrying real characters below"
                note: "drawn in the desktop's real row box (height = fontSize + 2, clip on), so a fallback ascent clips the line here exactly as it does live"
            }
            Row {
                spacing: root.gutter
                Repeater {
                    model: root.options
                    delegate: Card {
                        id: rowCard
                        required property var modelData
                        height: rowCol.implicitHeight + 12
                        Column {
                            id: rowCol
                            x: 6; y: 6
                            width: parent.width - 12
                            spacing: 0
                            Repeater {
                                model: root.realRows
                                delegate: Item {
                                    id: easyRow
                                    required property string modelData
                                    width: rowCol.width
                                    height: 17
                                    clip: true
                                    PixelText {
                                        anchors.verticalCenter: parent.verticalCenter
                                        font.family: rowCard.modelData.family
                                        text: easyRow.modelData
                                    }
                                }
                            }
                            Item { width: 1; height: 6 }
                            Rectangle { width: rowCol.width; height: 1; color: Wal.border }
                            Item { width: 1; height: 6 }
                            Repeater {
                                model: root.realRowsHard
                                delegate: Item {
                                    id: hardRow
                                    required property string modelData
                                    width: rowCol.width
                                    height: 17
                                    clip: true
                                    PixelText {
                                        anchors.verticalCenter: parent.verticalCenter
                                        font.family: rowCard.modelData.family
                                        text: hardRow.modelData
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ---------- 6. elision ----------
            SectionHead {
                label: "6. ELISION - THIS IS THE ONLY DIFFERENCE BETWEEN OPTION 2 AND OPTION 3"
                note: "the same strings elided to the same width. Option 2 ends in a one-cell ellipsis; options 1 and 3 end in three periods."
            }
            Row {
                spacing: root.gutter
                Repeater {
                    model: root.options
                    delegate: Card {
                        id: elCard
                        required property var modelData
                        height: elCol.implicitHeight + 12
                        Column {
                            id: elCol
                            x: 6; y: 6
                            width: parent.width - 12
                            spacing: 8
                            Repeater {
                                model: root.elideRows
                                delegate: Column {
                                    id: elItem
                                    required property string modelData
                                    spacing: 2
                                    Repeater {
                                        model: [220, 300, 380]
                                        delegate: Item {
                                            id: elBox
                                            required property int modelData
                                            width: elBox.modelData
                                            height: 17
                                            clip: true
                                            Rectangle {
                                                anchors.fill: parent
                                                color: "transparent"
                                                border.width: 1
                                                border.color: Wal.highlight
                                            }
                                            PixelText {
                                                x: 2
                                                anchors.verticalCenter: parent.verticalCenter
                                                width: parent.width - 4
                                                elide: Text.ElideRight
                                                font.family: elCard.modelData.family
                                                text: elItem.modelData
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 8 }
            Chrome {
                px: 15
                color: Wal.accent
                text: "Pick 1, 2 or 3 - or say what you want changed about this sheet and it will be redrawn."
            }
            Item { width: 1; height: 14 }
        }
    }
}
