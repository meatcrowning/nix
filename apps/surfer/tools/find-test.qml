import QtQuick
import QtQuick.Window
import QtWebEngine
import "../qml"

// Offscreen fixture for tools/find-test.py — the REAL FindBar.qml over a REAL
// WebEngineView, so the findText() plumbing under test is the one surfer ships.
// The profile is off the record on purpose: a persistent one would contend with
// the user's running browser for its Chromium profile directory.
Window {
    id: win
    width: 900
    height: 600
    visible: true

    property bool loaded: false

    WebEngineProfile { id: prof; offTheRecord: true }

    WebEngineView {
        id: page
        objectName: "page"
        anchors.fill: parent
        profile: prof
        onLoadingChanged: (info) => {
            if (info.status === WebEngineView.LoadSucceededStatus) win.loaded = true;
        }
    }

    FindBar {
        id: bar
        objectName: "findBar"
        view: page
    }

    // The SAME wiring Main.qml carries — find-test.py asserts that it is still
    // there, so this fixture cannot end up testing a hotkey the browser has lost.
    Connections {
        target: Hotkeys
        function onFind() { bar.openFind(); }
    }

    // stepping, reachable from the harness (QMetaObject.invokeMethod cannot pass
    // a bool through to a QML function)
    function stepNext() { bar.search(false); }
    function stepPrev() { bar.search(true); }
}
