import QtQuick
import "../../qmlcommon"

// The settings content as a scene of its own, for the Plasma face's
// "Configure painter…" dialog (pylib/kdeshell.py `dialog`).
//
// Same shape and same reason as ParamsPane.qml: `SettingsDrawer.qml` reaches
// the app through the id `root`, which QML resolves up the chain of creation
// contexts — and a file loaded as the root of its own QQuickWidget has no such
// chain. So this declares `id: root`, forwards the two properties that content
// actually reads, and hands the drawer its dialog clothes.
Item {
    id: root

    property Item app

    readonly property color fgAccent: app ? app.fgAccent : Theme.accent
    readonly property bool winActive: app ? app.winActive : true

    implicitWidth: 460
    implicitHeight: 430

    StyledBackground { anchors.fill: parent }

    SettingsDrawer {
        anchors.fill: parent
        anchors.margins: 8
        asDialog: true
        open: true
    }
}
