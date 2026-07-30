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
        width: parent.width
        height: 130
        placeholder: "positive"
        text: root.gen.positive
        onEdited: function (t) { var g = root.gen; g.positive = t; root.gen = g }
        onMenuRequested: (sx, sy, items) => panel.menuRequested(sx, sy, items)
    }

    PromptBox {
        width: parent.width
        height: 64
        placeholder: "negative"
        negative: true
        text: root.gen.negative
        onEdited: function (t) { var g = root.gen; g.negative = t; root.gen = g }
        onMenuRequested: (sx, sy, items) => panel.menuRequested(sx, sy, items)
    }
}
