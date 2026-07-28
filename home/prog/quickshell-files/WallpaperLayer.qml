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
// just this Item's geometry — a binding, not a freshly composited full-screen
// PNG per panel width, which is what hyprpaper needed and why it flashed.
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

    // ---- the blurred backdrop --------------------------------------------
    // Fills the whole monitor, behind everything, and NEVER moves or resizes.
    //
    // It exists for the gap: the sharp wallpaper tracks the COMMITTED width and
    // glides to it after the drag is released, so while the panel is being
    // narrowed there is a strip between the panel's new edge and the wallpaper's
    // old one. That strip used to be flat background — a black band opening up
    // as you dragged. Now the blur shows through it.
    //
    // The blur is PRE-COMPUTED, not a runtime effect: wal-prepare.sh caches a
    // 400px-wide real Gaussian per wallpaper and the panel just draws it. So it
    // costs one small static texture and nothing at all per frame — which is the
    // point, since it is on screen precisely while the compositor is busiest.
    //
    // The first version had no cached file: it decoded the wallpaper itself at
    // ~96px and let the GPU stretch that over the monitor, on the theory that a
    // bilinear upscale is a free blur. It is free, but it is not a blur — at 20x
    // magnification the picture was still plainly legible, with interpolation
    // facets. That path survives only as the FALLBACK below, for the moment
    // before wal-prepare.sh has produced the real one.
    readonly property int fallbackBlurSize: 96
    readonly property bool haveBlur: Wall.blurUrl.length > 0

    Image {
        anchors.fill: parent
        z: -1
        source: root.haveBlur ? Wall.blurUrl : Wall.url
        // PreserveAspectCrop over the FULL monitor, so the blur reads as a
        // continuation of the sharp copy rather than a squashed one.
        fillMode: Image.PreserveAspectCrop
        // The cached blur is already tiny and already smooth — decode it at its
        // natural size. Only the fallback needs shrinking to fake a blur.
        sourceSize.width: root.haveBlur ? 0 : root.fallbackBlurSize
        smooth: true
        asynchronous: true
        cache: false
        visible: source.toString().length > 0
    }

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

        // Gated on the reload settle. A fresh tree is built before the settings
        // have been read back and before the surface has been told its size, so
        // this Item is created at width 1 against a default-classic bar and only
        // then learns the truth — which, animated, is the wallpaper visibly
        // sliding across the screen on every theme or wallpaper change. During
        // the settle it snaps; after it, a committed panel width still glides.
        Behavior on x {
            enabled: !ViewMode.settling
            NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
        }
        Behavior on width {
            enabled: !ViewMode.settling
            NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
        }

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

    // ---- clicking the DESKTOP gives the keyboard back --------------------
    //
    // The task manager's filter box is the only thing on this desktop that
    // takes the keyboard, and "click anywhere outside it and it stops taking
    // keystrokes" has THREE cases, because three different things can be under
    // that click and only one of them was ever handled here:
    //
    //   the PANEL     — invisible to the compositor (a click inside a layer
    //                   surface moves no focus), so `shell.qml`'s catcher on
    //                   `barBody` has to see it. Already there.
    //   a WINDOW      — the compositor's, and already correct. Measured in a
    //                   nested Hyprland: the pointer merely ARRIVING over a
    //                   window revokes this layer's keyboard, Qt clears the
    //                   TextInput's `activeFocus` with it, and the caret and
    //                   the accent border go. No click needed and nothing for
    //                   the panel to do.
    //   the WALLPAPER — nobody's, which is the bug this block fixes.
    //                   `processMouseDownNormal` only calls `refocus()` when
    //                   the press lands on a window, so a press on a
    //                   BACKGROUND layer surface moves no focus at all: the
    //                   panel kept the keyboard and the box kept its caret
    //                   indefinitely, and the only way out was a click back
    //                   inside the panel. This surface is OURS, so the click
    //                   is ours to see — the compositor never has to.
    //
    // Handing the keyboard back from HERE is the safe direction, and that is
    // not an assumption: `refocusLastWindow` searches only the OVERLAY and TOP
    // layers, so it does not find this Background surface under the pointer
    // and falls through to the last focused window. Measured on the event
    // socket — `activewindow>>,` for 2 ms, then `activewindow>>` the window.
    // Doing the same with the pointer over the PANEL is what strands the
    // keyboard on nothing; see `Procs.filterLatch` for that half.
    //
    // Enabled — and so opaque to events — only while the box actually holds
    // focus, and it declines the press it saw, so the wallpaper is inert the
    // rest of the time.
    MouseArea {
        anchors.fill: parent
        z: 1
        enabled: Procs.filterFocus
        acceptedButtons: Qt.AllButtons
        onPressed: (mouse) => {
            Procs.blurFilter();
            mouse.accepted = false;
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
        //
        // It is also SYNCHRONOUS, and that is what makes a reload look like a
        // state change in place rather than a re-entry. A reload rebuilds this
        // window's QML tree while the compositor keeps showing the OLD surface's
        // last buffer, so the only thing that can go wrong is the new tree
        // committing a frame it has not painted the wallpaper into yet — which
        // is a full-screen flash of Theme.bg. Measured on a forced reload before
        // this: the Image reached Image.Ready 103 ms after the tree completed
        // (status Loading at both Qt.callLater and a 0 ms Timer). A blocking
        // decode costs ~25-35 ms of one reload pass, on a screen nothing is
        // animating on, and puts the picture in the FIRST frame.
        if (!_front.source.toString().length) {
            _front.loadNow(url, mode);
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
    // Wall.loadNow() FIRST: a singleton completes at the end of the load pass, so
    // Wall.url is still empty here on every reload unless it is forced. Without
    // it the source was assigned ~20 ms after this pass — too late for the first
    // frame no matter how fast the decode is.
    Component.onCompleted: {
        Wall.loadNow();
        _apply(Wall.url, Wall.mode);
        if (_reports) Wall.firstPaint = _statusName(_front.status);
    }

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
    function _statusName(s: int): string { return ["null", "ready", "loading", "error"][s] || "?"; }
    function _report() {
        if (!_reports) return;
        Wall.frontStatus = _statusName(_front.status);
        Wall.frontUrl = String(_front.source);
    }
    Connections {
        target: root._front
        function onStatusChanged() { root._report(); }
        function onSourceChanged() { root._report(); }
    }
    on_ShowAChanged: _report()
}
