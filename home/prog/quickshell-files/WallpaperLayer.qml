import QtQuick
import Quickshell
import Quickshell.Wayland

// The wallpaper, drawn by the panel instead of by hyprpaper (see Wall.qml for
// why). One full-screen Background-layer surface per monitor.
//
// THE POINT OF DOING IT HERE: the art is centred in the VISIBLE desktop — the
// screen minus whatever the panel covers — rather than on the monitor. In dock
// mode the panel takes a quarter to a third of the width, and centring on the
// monitor would bury the subject of the picture behind it. That recentring is
// just this Item's geometry, so it follows the panel edge live, at frame rate,
// while the edge is being dragged. hyprpaper needed a freshly composited
// full-screen PNG per panel width to achieve the same thing, and flashed.
PanelWindow {
    id: root
    required property var modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    // Ignore everyone's exclusive zones — the wallpaper must cover the WHOLE
    // monitor, including the strip under the panel. (Setting exclusiveZone here
    // would select the "Normal" mode and shrink this surface; see EdgeGrip.qml.)
    exclusionMode: ExclusionMode.Ignore
    color: Theme.bg

    WlrLayershell.layer: WlrLayer.Background
    WlrLayershell.namespace: "qs-wallpaper"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    readonly property bool barLeft: SettingsStore.d.barEdge === "left"

    // The desktop the user can actually see. Everything is centred in HERE.
    //
    // Tracks the COMMITTED width (barWidth), not the live drag. Re-centring the
    // art on every pointer event means re-cropping a full-screen texture at
    // pointer rate for an image nobody is looking at yet — the panel edge is
    // what the eye follows during a drag. So it waits for the release and then
    // glides to the new centre, which costs one animation instead of a whole
    // drag's worth of frames.
    Item {
        id: visibleArea
        y: 0
        height: parent.height
        x: root.barLeft ? ViewMode.barWidth : 0
        width: Math.max(1, parent.width - ViewMode.barWidth)
        clip: true

        Behavior on x { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }

        // The two frames of the cross-fade. Only one is showing at a time; a new
        // wallpaper is loaded into whichever is hidden and revealed once it has
        // decoded, so the swap never shows a half-painted or empty frame.
        WallpaperImage {
            id: imgA
            anchors.fill: parent
            showing: root._showA
            decodeW: root.screen ? root.screen.width : 1920
            decodeH: root.screen ? root.screen.height : 1080
        }
        WallpaperImage {
            id: imgB
            anchors.fill: parent
            showing: !root._showA
            decodeW: root.screen ? root.screen.width : 1920
            decodeH: root.screen ? root.screen.height : 1080
        }
    }

    // ---- cross-fade bookkeeping -----------------------------------------
    property bool _showA: true
    readonly property var _front: _showA ? imgA : imgB
    readonly property var _back: _showA ? imgB : imgA

    function _apply(url, mode) {
        if (!url.length) return;
        if (_front.source == url && _front.mode === mode) return;
        // First paint: no fade, just show it. Fading up from an empty layer at
        // login would read as the desktop loading in.
        if (!_front.source.toString().length) {
            _front.mode = mode;
            _front.source = url;
            return;
        }
        _back.mode = mode;
        _back.source = url;      // revealed by onReady below once decoded
    }

    Connections {
        target: Wall
        function onUrlChanged() { root._apply(Wall.url, Wall.mode); }
        function onModeChanged() { root._apply(Wall.url, Wall.mode); }
    }
    Component.onCompleted: _apply(Wall.url, Wall.mode)

    Connections {
        target: imgA
        function onReady() { if (!root._showA && imgA.source == Wall.url) root._showA = true; }
    }
    Connections {
        target: imgB
        function onReady() { if (root._showA && imgB.source == Wall.url) root._showA = false; }
    }

    // Publish the visible frame's load state for `qs ipc call wallpaper status`.
    // Only the first screen reports, so the value means one thing on a
    // multi-monitor setup rather than whichever window updated last.
    readonly property bool _reports: screen === Quickshell.screens[0]
    function _report() {
        if (!_reports) return;
        Wall.frontStatus = ["null", "ready", "loading", "error"][_front.status] || "?";
        Wall.frontUrl = String(_front.source);
    }
    Connections {
        target: root._front
        function onStatusChanged() { root._report(); }
        function onSourceChanged() { root._report(); }
    }
    on_ShowAChanged: _report()
}
