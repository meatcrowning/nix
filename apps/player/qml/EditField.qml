import QtQuick

// ONE-LINE TEXT ENTRY, so the app has one and not three.
//
// The three boxes in the rule editor (the playlist's name, a rule's value, the
// track limit) were each a `Theme.bgAlt` Rectangle with a hand-drawn focus
// border and a raw `TextInput` in it, repeated verbatim. That is the right
// control for the pixel face — docs/DESIGN.md §9.1, and `Theme.editorFont`
// carries the NoAntialias pin an editable item needs (§2.2) — and the wrong one
// in a Plasma session, where a text field is the single most recognisable
// widget a style owns. A component is what lets `+plasma/EditField.qml` be the
// KStyle's real `TextField` with no call site knowing (main.py ->
// select_plasma_files).
//
// The API is deliberately `TextField`'s own — `text`, `placeholderText`,
// `validator`, `maximumLength`, `textEdited`, `accepted` — so the Plasma twin
// inherits nearly all of it rather than restating it. `escaped()` is the one
// addition: Escape has to reach the OWNER (cancel the editor), and a `Keys`
// handler at the call site would land on the wrapper here and never on the
// TextInput inside it.
Rectangle {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    property alias text: input.text
    property alias placeholderText: ph.text
    property alias validator: input.validator
    property alias maximumLength: input.maximumLength
    // Handed in already faded by the owning pane (docs/DESIGN.md §3.1.1).
    property color fgText: Theme.text
    property color fgAccent: Theme.accent

    signal textEdited()
    signal accepted()
    signal escaped()

    // TextField's own two, forwarded past the wrapper: an owner that opens the
    // editor puts the caret in the name box and selects what is there, and on
    // the Item root here both calls would land on the frame rather than on the
    // TextInput inside it. `+plasma/EditField.qml` inherits both for real.
    function selectAll() { input.selectAll(); }
    // NOT called `forceActiveFocus`: that is Item's own method, and declaring a
    // function over it makes the component load with no error and then behave
    // as if the body it is in had stopped running.
    function focusInput() { input.forceActiveFocus(); }

    implicitWidth: 120
    implicitHeight: Theme.lineHeight + 9   // the 24 the three boxes each had

    color: Theme.bgAlt
    radius: Theme.rounding
    border.width: Theme.ctrlBorder
    border.color: input.activeFocus ? root.fgAccent : Theme.border

    TextInput {
        id: input
        anchors.fill: parent
        anchors.margins: 4
        verticalAlignment: TextInput.AlignVCenter
        font: (typeof DeskStyle !== "undefined" && DeskStyle
                       && typeof DeskStyle.editorFontForScale === "function")
                      ? DeskStyle.editorFontForScale(Screen.devicePixelRatio)
                      : Theme.editorFontForScale(Screen.devicePixelRatio) // whole QFont, including Kitty cell spacing
        renderType: Text.NativeRendering
        color: root.fgText
        clip: true
        onTextEdited: root.textEdited()
        onAccepted: root.accepted()
        Keys.onEscapePressed: root.escaped()

        PixelText {
            id: ph
            visible: input.text === ""
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.dim
        }
    }
}
