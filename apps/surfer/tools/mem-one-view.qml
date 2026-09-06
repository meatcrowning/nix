import QtQuick
import QtQuick.Window
import QtWebEngine

// True one-view fixture for mem-test.py.  Keeping the profile/root alive while
// unloading only the Loader separates per-view teardown from global WebEngine
// state retained by the application engine.
Window {
    id: root
    width: 1280
    height: 800
    visible: true

    property bool viewAlive: false
    property bool loaded: false
    property alias view: viewLoader.item

    WebEngineProfile {
        id: prof
        objectName: "memProfile"
        storageName: "mem-one-view"
        offTheRecord: false
    }

    Loader {
        id: viewLoader
        objectName: "viewLoader"
        anchors.fill: parent
        active: root.viewAlive
        sourceComponent: WebEngineView {
            objectName: "win0"
            profile: prof
            onLoadingChanged: function(load) {
                if (load.status === WebEngineView.LoadSucceededStatus)
                    root.loaded = true
            }
        }
    }
}
