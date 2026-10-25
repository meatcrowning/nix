import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../qmlcommon"

Panel {
    id: panel
    title: "Prompt"
    property bool pillsWanted: Prefs.get("prompt.pills") === true
    readonly property bool pillsAvailable: root.gen.promptTransform === "danbooru"
    // The compact capsule is clearer than spending the little header on two
    // words, and it never crowds the title or model-status badge.
    headerActionLabel: pillsAvailable ? "pill view" : ""
    headerActionLit: pillsWanted
    headerActionPill: true
    onHeaderAction: {
        pillsWanted = !pillsWanted
        Prefs.set("prompt.pills", pillsWanted)
    }

    // CTRL+Z IN TAG VIEW. The text boxes have TextEdit's own undo; the pill
    // views have none of that machinery, and while they are showing there is no
    // TextEdit on screen for the key to belong to. One shortcut for both views,
    // aimed at whichever was edited last, so the two can never be ambiguous.
    function undoTarget() {
        var best = null
        var all = [positive.pills, negative.pills]
        for (var i = 0; i < all.length; i++) {
            var v = all[i]
            if (!v || !v.visible || !v.canUndo || v.editingId !== -1) continue
            if (!best || v.touchedAt > best.touchedAt) best = v
        }
        return best
    }

    Shortcut {
        sequences: ["Ctrl+Z"]
        enabled: panel.pillsAvailable && panel.pillsWanted
                 && panel.undoTarget() !== null
        onActivated: { var v = panel.undoTarget(); if (v) v.undo() }
    }

    //: Forwarded from both boxes to Main.qml, which owns the one context menu.
    signal menuRequested(real sx, real sy, var items)
    // Anima wants a single line; the editor still keeps your line breaks, they
    // are only collapsed on the way out.
    badge: root.gen.promptTransform === "single_line" ? "sent as one line" : ""

    KineticFlickable {
        width: parent.width
        height: wildcardRow.implicitHeight + wildcardScroll.implicitHeight
        contentWidth: wildcardRow.width
        contentHeight: wildcardRow.implicitHeight
        clip: true
        ScrollBar.horizontal: ScrollBar { id: wildcardScroll }
        Row {
            id: wildcardRow
            spacing: 2
            Repeater {
                model: App.wildcardNames
                WildcardButton {
                    required property string modelData
                    name: modelData
                    editable: !root.comparisonMode
                    onInserted: {
                        panel.pillsWanted = false
                        positive.insertWildcard(modelData)
                    }
                }
            }
        }
    }

    TokenProbe { id: positiveTokens; objectName: "positiveTokenProbe"; text: root.gen.positive; active: App.layoutSupport }
    TokenProbe { id: negativeTokens; objectName: "negativeTokenProbe"; text: root.gen.negative; active: App.layoutSupport }
    PromptWriter { scope: "positive"; tokenProbe: positiveTokens }

    PromptBox {
        id: positive
        tokenBoundaries: positiveTokens.boundaries
        tokenMarksReady: positiveTokens.count >= 0
        width: parent.width
        // Completion can assist mixed prose/tag prompts without changing
        // the family's generation-time text transform.
        tagsEnabled: App.tagCompletion
        pillMode: panel.pillsAvailable && panel.pillsWanted
        tagPopup: root.tagPopup
        // Dragged by its bottom edge and remembered, per box (Panel's own
        // collapsed state is persisted the same way).
        boxHeight: Prefs.get("prompt.posH") > 0 ? Prefs.get("prompt.posH") : 130
        placeholder: "Positive"
        value: root.gen.positive
        onEdited: function (t) { root.set("positive", t) }
        onResized: function (h) { Prefs.set("prompt.posH", h) }
        onMenuRequested: (sx, sy, items) => panel.menuRequested(sx, sy, items)
    }

    // NO NEGATIVE PROMPT FOR VIDEO OR FOR EDIT. MiniMaxH3ImageToVideo takes the prompt
    // itself and produces the conditioning — there is no second CLIPTextEncode
    // for a negative to reach, so a box for one would be typing into nothing.
    // The Klein edit graph has the same shape from the other direction: its
    // negative conditioning is the POSITIVE one zeroed out (ConditioningZeroOut
    // -> ReferenceLatent), so there is nowhere for a second prompt to go.
    //
    // Height 0 as well as invisible, and it stays that way: `Panel` sizes
    // itself from the Column's `implicitHeight` now (which skips a hidden child
    // outright), but a box that folds to nothing is also what stops a stale
    // height reappearing the moment it is shown again. The blank this used to
    // leave under the prompt — and the panel that would then only ever GROW —
    // is the story in `Panel.qml`.
    PromptWriter {
        scope: "negative"
        tokenProbe: negativeTokens
        visible: !App.isVideo && (!App.isEdit || App.editSampling)
    }
    PromptBox {
        id: negative
        tokenBoundaries: negativeTokens.boundaries
        tokenMarksReady: negativeTokens.count >= 0
        width: parent.width
        // The negative is tags too — `lowres, worst quality` — so it completes
        // on the same families the positive does.
        tagsEnabled: App.tagCompletion
        pillMode: panel.pillsAvailable && panel.pillsWanted
        tagPopup: root.tagPopup
        visible: !App.isVideo && (!App.isEdit || App.editSampling)
        boxHeight: Prefs.get("prompt.negH") > 0 ? Prefs.get("prompt.negH") : 64
        placeholder: "Negative"
        negative: true
        value: root.gen.negative
        onEdited: function (t) { root.set("negative", t) }
        onResized: function (h) { Prefs.set("prompt.negH", h) }
        onMenuRequested: (sx, sy, items) => panel.menuRequested(sx, sy, items)
    }
    Column {
        width: parent.width
        visible: App.layoutSupport
        spacing: 6
        function seedMode(random) {
            root.set("seed", random ? -1 : (root.gen.seed < 0 ? App.freshSeed() : root.gen.seed))
            root.set("randomSeed", random)
            root.set("reuseSeed", false)
        }
        RowLayout {
            width: parent.width
            spacing: 4
            Button {
                icon.name: "media-playlist-shuffle"
                display: AbstractButton.IconOnly
                implicitWidth: implicitHeight
                Accessible.name: "Randomize seed"
                ToolTip.visible: hovered
                ToolTip.text: "Randomize seed for each generation"
                onClicked: parent.parent.seedMode(true)
            }
            Button {
                icon.name: "document-new"
                display: AbstractButton.IconOnly
                implicitWidth: implicitHeight
                Accessible.name: "New fixed seed"
                ToolTip.visible: hovered
                ToolTip.text: "New fixed seed"
                onClicked: {
                    root.set("seed", App.freshSeed())
                    parent.parent.seedMode(false)
                }
            }
            ComboBox {
                model: ["Fixed", "Random", "Reuse last"]
                currentIndex: root.gen.reuseSeed ? 2 : root.gen.randomSeed ? 1 : 0
                onActivated: index => {
                    if (index === 2) {
                        root.set("randomSeed", false)
                        root.set("reuseSeed", true)
                        if (App.lastSeed >= 0) root.set("seed", App.lastSeed)
                    } else parent.parent.seedMode(index === 1)
                }
            }
            PixelText {
                text: "Seed number"
                Layout.alignment: Qt.AlignVCenter
            }
            SeedInput {
                Layout.fillWidth: true
                Layout.minimumWidth: 40
                Layout.preferredWidth: 100
                enabled: !root.gen.randomSeed && !root.gen.reuseSeed
                value: root.gen.reuseSeed && App.lastSeed >= 0 ? App.lastSeed : root.gen.seed
                onEdited: value => root.set("seed", value)
            }
        }
        Row {
            width: parent.width
            spacing: 4
            PixelText { text: "AR"; anchors.verticalCenter: parent.verticalCenter }
            Spin { width: 34; value: root.gen.aspectW; from: 1; to: 999; step: 1; onEdited: v => { root.set("aspectW", Math.round(v)); root.recomputeDims() } }
            PixelText { text: ":"; anchors.verticalCenter: parent.verticalCenter }
            Spin { width: 34; value: root.gen.aspectH; from: 1; to: 999; step: 1; onEdited: v => { root.set("aspectH", Math.round(v)); root.recomputeDims() } }
            PixelText { text: "MP"; anchors.verticalCenter: parent.verticalCenter }
            Spin { width: 64; value: root.gen.megapixels; from: .05; to: 16; step: .1; decimals: 6; trimZeros: true; onEdited: v => { root.set("megapixels", v); root.recomputeDims() } }
            PixelText { text: root.gen.width + " × " + root.gen.height; anchors.verticalCenter: parent.verticalCenter }
        }
    }
    Loader {
        width: parent.width
        height: active && item ? item.implicitHeight : 0
        active: App.layoutSupport
        visible: active
        sourceComponent: LayoutEditor { generation: root.gen }
    }

}
