import QtQuick

// Vertical titlebar for one window, as a plain Item inside TitlebarOverlay's
// single fullscreen surface (NOT its own layer surface — moving an Item in
// an existing scene is one frame of latency and no configure round-trip, so
// titlebars track drags as tightly as a Wayland client can).
//
// modelData is the window ADDRESS (a stable string — see WindowTracker.qml
// for why identity and geometry are split); everything positional comes
// from WindowTracker.geometry so a moving window slides this item around
// instead of recreating it.
//
// The content only renders inside geo.intervals — the y-ranges not covered
// by windows stacked above this one — via clipped viewport slices, each
// holding its own copy of the Face. That clips the titlebar exactly where
// another window overlaps it, as if the titlebar were underneath. The
// slices are also what TitlebarOverlay's input mask is built from, so
// clicks over the covered parts fall through to the window on top.
//
// Top to bottom: close, maximize (fill-workspace-area toggle, not
// fullscreen), then the title rotated vertical.
Item {
    id: tb
    required property var modelData

    readonly property var geo: WindowTracker.geometry[modelData] ||
        ({ x: 0, y: 0, width: 0, height: 0, title: "", focused: false, intervals: [] })
    readonly property bool maximized: !!WindowTracker.maximizedState[modelData]

    signal slicesChanged()

    // Hyprland draws the 2px window border OUTSIDE at/size, so overshoot by
    // windowBorderWidth top and bottom to sit flush with the window's frame,
    // and let our own left border paint exactly over the window's right
    // border. x is clamped at the panel's edge: dragging a window far right
    // slides the titlebar over the window's own right edge rather than into
    // the bar — the window itself is never touched.
    x: Math.min(geo.x + geo.width,
        (parent ? parent.width : 0) - Theme.barWidth - WindowTracker.titlebarWidth)
    y: geo.y - Theme.windowBorderWidth
    width: WindowTracker.titlebarWidth
    height: geo.height + Theme.windowBorderWidth * 2

    function sliceCount() { return slices.count; }
    function sliceAt(i) { return slices.itemAt(i); }

    // The full titlebar visuals, instantiated once per visible slice.
    component Face: Item {
        Rectangle {
            anchors.fill: parent
            color: Theme.bg
            border.width: Theme.windowBorderWidth
            // Track the window's own frame: accent for the focused window,
            // Hyprland's inactive_border grey for everything else.
            border.color: tb.geo.focused ? Theme.windowBorder : Theme.windowBorderInactive
        }

        Column {
            anchors { top: parent.top; horizontalCenter: parent.horizontalCenter }
            anchors.topMargin: 2
            spacing: 2

            // ---- close ----
            Rectangle {
                width: Theme.wsCell
                height: Theme.wsCell
                color: closeMouse.containsMouse ? Theme.bgAlt : "transparent"
                border.width: closeMouse.containsMouse ? 2 : 1
                border.color: closeMouse.containsMouse ? Theme.crit : Theme.border

                PixelText {
                    anchors.centerIn: parent
                    text: "x"
                    color: closeMouse.containsMouse ? Theme.crit : Theme.textDim
                }

                MouseArea {
                    id: closeMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: WindowTracker.closeWindow(tb.modelData)
                }
            }

            // ---- maximize ----
            Rectangle {
                width: Theme.wsCell
                height: Theme.wsCell
                color: (tb.maximized || maxMouse.containsMouse) ? Theme.bgAlt : "transparent"
                border.width: (tb.maximized || maxMouse.containsMouse) ? 2 : 1
                border.color: (tb.maximized || maxMouse.containsMouse) ? Theme.accent : Theme.border

                Rectangle {
                    anchors.centerIn: parent
                    width: Theme.wsCell - 16
                    height: width
                    color: "transparent"
                    border.width: 1
                    border.color: tb.maximized ? Theme.accent : Theme.textDim
                }

                MouseArea {
                    id: maxMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: WindowTracker.toggleMaximize(tb.modelData)
                }
            }
        }

        // ---- vertical title, below the buttons, filling the rest ----
        Item {
            id: titleArea
            anchors.fill: parent
            anchors.topMargin: (Theme.wsCell + 2) * 2 + 4

            Text {
                text: tb.geo.title
                font.family: Theme.font
                font.pixelSize: Theme.fontSize
                color: Theme.textDim
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignLeft
                // Pre-rotation: width is the available vertical run (what
                // gets elided against); height is the natural single-line
                // text height. Rotating -90 about the top-left corner then
                // swings the item to x in [0, implicitHeight], y in
                // [-width, 0] — the "y: width" shift below brings that back
                // to [0, width], i.e. back inside titleArea. Net effect:
                // title reads bottom-to-top.
                width: titleArea.height
                rotation: -90
                transformOrigin: Item.TopLeft
                x: (WindowTracker.titlebarWidth - implicitHeight) / 2
                y: width
            }
        }
    }

    Repeater {
        id: slices
        model: tb.geo.intervals
        onItemAdded: tb.slicesChanged()
        onItemRemoved: tb.slicesChanged()

        // One clipped viewport per visible interval; the Face inside is
        // shifted up so its content lines up as if unclipped.
        Item {
            id: slice
            required property var modelData
            y: modelData[0]
            width: tb.width
            height: modelData[1] - modelData[0]
            clip: true

            Face {
                y: -slice.modelData[0]
                width: tb.width
                height: tb.height
            }
        }
    }
}
