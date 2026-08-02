import QtQuick
import QtQuick.Window
import QtWebEngine

// Memory-measurement fixture for tools/mem-test.py — a mini stand-in for
// surfer's Main.qml: several WebEngineViews sharing one persistent profile,
// stacked so only tab 0 is "on screen" (visible) and the rest are background
// tabs. It lets the harness measure what hidden tabs' renderers pin, and what
// freezing/discarding recovers, without loading the whole browser.
//
// The root is an offscreen Window (like find-test.qml) because WebEngineView
// needs a window to render and navigate; `visible: true` here is an offscreen
// window, never a monitor one — QT_QPA_PLATFORM=offscreen has no physical
// display at all. The views are declared explicitly (a Repeater does not
// instantiate delegates in this offscreen context, measured) and each is found
// by objectName (winN) from Python, which loads it and drives its
// lifecycleState directly — so the measurement is of the ENGINE, not of any
// one undoable wiring.
Window {
    id: root
    width: 1280
    height: 800
    visible: true

    property int loaded: 0
    property bool allLoaded: false

    WebEngineProfile {
        id: prof
        objectName: "memProfile"
        storageName: "mem"
        offTheRecord: false
    }

    WebEngineView {
        id: v0
        objectName: "win0"
        visible: true
        width: root.width
        height: root.height
        profile: prof
        onLoadingChanged: function(load) {
            if (load.status === WebEngineView.LoadSucceededStatus) root.loaded += 1
        }
    }
    Text { objectName: "tok"; Component.onCompleted: {
        text = "" + WebEngineView.LifecycleState.Active + "|" + WebEngineView.LifecycleState.Discarded + "|" + WebEngineView.Frozen
    } }
    WebEngineView {
        id: v1
        objectName: "win1"
        visible: false
        width: root.width
        height: root.height
        profile: prof
        onLoadingChanged: function(load) {
            if (load.status === WebEngineView.LoadSucceededStatus) root.loaded += 1
        }
    }
    WebEngineView {
        id: v2
        objectName: "win2"
        visible: false
        width: root.width
        height: root.height
        profile: prof
        onLoadingChanged: function(load) {
            if (load.status === WebEngineView.LoadSucceededStatus) root.loaded += 1
        }
    }
    WebEngineView {
        id: v3
        objectName: "win3"
        visible: false
        width: root.width
        height: root.height
        profile: prof
        onLoadingChanged: function(load) {
            if (load.status === WebEngineView.LoadSucceededStatus) root.loaded += 1
        }
    }
    WebEngineView {
        id: v4
        objectName: "win4"
        visible: false
        width: root.width
        height: root.height
        profile: prof
        onLoadingChanged: function(load) {
            if (load.status === WebEngineView.LoadSucceededStatus) root.loaded += 1
        }
    }
    WebEngineView {
        id: v5
        objectName: "win5"
        visible: false
        width: root.width
        height: root.height
        profile: prof
        onLoadingChanged: function(load) {
            if (load.status === WebEngineView.LoadSucceededStatus) root.loaded += 1
        }
    }

    onLoadedChanged: { root.allLoaded = (root.loaded >= 6) }
}
