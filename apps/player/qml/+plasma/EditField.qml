import QtQuick
import QtQuick.Controls

// EditField, in a Plasma session: the KStyle's own `TextField` — Oxygen's
// sunken frame, its focus glow, its selection colours and its context menu,
// rather than a `bgAlt` rectangle with a border we colour ourselves.
//
// Almost nothing to restate: ../EditField.qml's API is TextField's own on
// purpose, so `text`, `placeholderText`, `validator`, `maximumLength`,
// `textEdited` and `accepted` are all inherited here. The colour tones are
// accepted and IGNORED, like every other `+plasma` twin's — a KDE field's
// colours are the scheme's — and the font is the style's too, so nothing pins
// NoAntialias: that pin exists to keep a PIXEL face crisp in an editable item
// (docs/DESIGN.md §2.2), and the face here is whatever System Settings holds.
TextField {
    id: root
    property string face: "plasma"
    property color fgText: Theme.text
    property color fgAccent: Theme.accent

    signal escaped()

    // ../EditField.qml's, for the same call site; here the TextField IS the
    // input, so it is the native call.
    function focusInput() { root.forceActiveFocus(); }

    implicitWidth: 120
    Keys.onEscapePressed: root.escaped()
}
