import QtQuick

Panel {
    id: panel
    title: "prompt"
    property bool pillsWanted: Prefs.get("prompt.pills") === true
    readonly property bool pillsAvailable: root.gen.promptTransform === "danbooru"
    headerActionLabel: pillsAvailable ? (pillsWanted ? "[ text ]" : "[ tags ]") : ""
    headerActionLit: pillsWanted
    onHeaderAction: {
        pillsWanted = !pillsWanted
        Prefs.set("prompt.pills", pillsWanted)
    }

    //: Forwarded from both boxes to Main.qml, which owns the one context menu.
    signal menuRequested(real sx, real sy, var items)
    // Anima wants a single line; the editor still keeps your line breaks, they
    // are only collapsed on the way out.
    badge: root.gen.promptTransform === "single_line" ? "sent as one line" : ""

    PromptBox {
        id: positive
        width: parent.width
        // TAG COMPLETION IS A DANBOORU-FAMILY FEATURE. `danbooru` is the
        // transform that says this prompt is written in the site's tags, which
        // is the only prompt a tag list belongs over (Anima's, today).
        tagsEnabled: root.gen.promptTransform === "danbooru"
        pillMode: panel.pillsAvailable && panel.pillsWanted
        tagPopup: root.tagPopup
        // Dragged by its bottom edge and remembered, per box (Panel's own
        // collapsed state is persisted the same way).
        boxHeight: Prefs.get("prompt.posH") > 0 ? Prefs.get("prompt.posH") : 130
        placeholder: "positive"
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
    PromptBox {
        id: negative
        width: parent.width
        // The negative is tags too — `lowres, worst quality` — so it completes
        // on the same families the positive does.
        tagsEnabled: root.gen.promptTransform === "danbooru"
        pillMode: panel.pillsAvailable && panel.pillsWanted
        tagPopup: root.tagPopup
        visible: !App.isVideo && !App.isEdit
        boxHeight: Prefs.get("prompt.negH") > 0 ? Prefs.get("prompt.negH") : 64
        placeholder: "negative"
        negative: true
        value: root.gen.negative
        onEdited: function (t) { root.set("negative", t) }
        onResized: function (h) { Prefs.set("prompt.negH", h) }
        onMenuRequested: (sx, sy, items) => panel.menuRequested(sx, sy, items)
    }
}
