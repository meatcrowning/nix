import QtQuick
import QtQuick.Controls as QQC

// A job-row verb in a Plasma session: a real KStyle button, the same as every
// other button in the window (docs/DESIGN.md §7.6 — where an app can be a real
// KDE window, it is one). Not flat: a flat KStyle button draws no relief until
// hover, and these sit on a frame where the relief is what makes them findable.
//
// Same API as ../JobVerb.qml — `label`, `lit`, `enabled`, `clicked()` — so
// JobRow is untouched. `lit` is the KStyle's own CHECKED button: a decision
// card leaves the option he took held down among its greyed siblings, and in a
// Plasma session that state belongs to the style, not to a colour of ours
// (docs/DESIGN.md §7.6).
Item {
    id: root
    property string face: "plasma"
    property alias label: btn.text
    property bool lit: false

    signal clicked()

    implicitWidth: btn.implicitWidth
    implicitHeight: btn.implicitHeight
    width: implicitWidth
    height: implicitHeight

    QQC.Button {
        id: btn
        anchors.fill: parent
        padding: 4
        // Checkable only while it is a record of a choice: an ordinary verb
        // (the jobs tray's `log` / `stop`) must not start toggling.
        checkable: root.lit
        checked: root.lit
        enabled: root.enabled
        onClicked: root.clicked()
    }
}
