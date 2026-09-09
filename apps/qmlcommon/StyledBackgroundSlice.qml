import QtQuick

// A clipped piece of the same KDE-rendered background used by the view root.
// Pass coordinates in that root's space: the image is translated upward/left,
// so Oxygen's lighting does not restart at the edge of a nested section.
Item {
    id: slice
    property real sourceX: 0
    property real sourceY: 0
    property real sourceWidth: width + sourceX
    property real sourceHeight: height + sourceY
    clip: true

    StyledBackground {
        x: -slice.sourceX
        y: -slice.sourceY
        width: slice.sourceWidth
        height: slice.sourceHeight
    }
}
