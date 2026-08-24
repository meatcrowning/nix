import QtQuick
import QtQuick.Controls as QQC

// A job-row verb in a Plasma session: a real KStyle button, the same as every
// other button in the window (docs/DESIGN.md §7.6 — where an app can be a real
// KDE window, it is one). Not flat: a flat KStyle button draws no relief until
// hover, and these sit on a frame where the relief is what makes them findable.
//
// Same API as ../JobVerb.qml — `label`, `clicked()` — so JobRow is untouched.
Item {
    id: root
    property string face: "plasma"
    property alias label: btn.text

    signal clicked()

    implicitWidth: btn.implicitWidth
    implicitHeight: btn.implicitHeight
    width: implicitWidth
    height: implicitHeight

    QQC.Button {
        id: btn
        anchors.fill: parent
        padding: 4
        onClicked: root.clicked()
    }
}
