import QtQuick

Panel {
    id: panel
    title: "prompt"

    //: Forwarded from both boxes to Main.qml, which owns the one context menu.
    signal menuRequested(real sx, real sy, var items)
    // Anima wants a single line; the editor still keeps your line breaks, they
    // are only collapsed on the way out.
    badge: root.gen.promptTransform === "single_line" ? "sent as one line" : ""

    PromptBox {
        id: positive
        width: parent.width
        // Dragged by its bottom edge and remembered, per box (Panel's own
        // collapsed state is persisted the same way).
        boxHeight: Prefs.get("prompt.posH") > 0 ? Prefs.get("prompt.posH") : 130
        placeholder: "positive"
        value: root.gen.positive
        onEdited: function (t) { root.set("positive", t) }
        onResized: function (h) { Prefs.set("prompt.posH", h) }
        onMenuRequested: (sx, sy, items) => panel.menuRequested(sx, sy, items)
    }

    // NO NEGATIVE PROMPT FOR VIDEO. MiniMaxH3ImageToVideo takes the prompt
    // itself and produces the conditioning — there is no second CLIPTextEncode
    // for a negative to reach, so a box for one would be typing into nothing.
    //
    // Height 0 as well as invisible: a Column skips a hidden child when it
    // POSITIONS, but the panel sizes itself from `childrenRect`, which still
    // counted the box that was not there — a hand-sized blank under the prompt
    // in every video job.
    PromptBox {
        id: negative
        width: parent.width
        visible: !App.isVideo
        boxHeight: Prefs.get("prompt.negH") > 0 ? Prefs.get("prompt.negH") : 64
        placeholder: "negative"
        negative: true
        value: root.gen.negative
        onEdited: function (t) { root.set("negative", t) }
        onResized: function (h) { Prefs.set("prompt.negH", h) }
        onMenuRequested: (sx, sy, items) => panel.menuRequested(sx, sy, items)
    }
}
