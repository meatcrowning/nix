import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property bool filled: false
    property color color: filled ? Theme.accent : Theme.textDim
    implicitWidth: 12
    implicitHeight: 12
    Shape {
        width: 24; height: 24
        scale: Math.min(root.width, root.height) / 24
        transformOrigin: Item.TopLeft
        ShapePath {
            strokeColor: root.color
            strokeWidth: 1.5
            fillColor: root.filled ? root.color : "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: "M12 20 C9 17 3 13 3 8 C3 3 9 2 12 7 C15 2 21 3 21 8 C21 13 15 17 12 20 Z" }
        }
    }
}
