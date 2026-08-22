import QtQuick
import QtQuick.Controls as QQC

// Slider, in a Plasma session: the style's own slider — Oxygen's groove, its
// handle and its focus ring — instead of the two rectangles and a box
// ../Slider.qml draws.
//
// Same API (from/to/value/step, `moved(v)`), and STILL CONTROLLED: a QQC2
// Slider owns its `value`, and a plain binding onto `root.value` would be BROKEN
// the first time the user dragged it — after which the parent writing the value
// back would no longer reach the handle. A `Binding` object re-applies instead,
// so the source of truth stays where it was.
Item {
    id: root
    property string face: "plasma"
    property real from: 0
    property real to: 10
    property real value: 0
    property real step: 1
    property color fgAccent: Theme.accent
    signal moved(real v)

    implicitWidth: 150
    implicitHeight: bar.implicitHeight
    height: implicitHeight

    QQC.Slider {
        id: bar
        anchors.fill: parent
        from: root.from
        to: root.to
        stepSize: root.step
        snapMode: QQC.Slider.SnapAlways
        onMoved: root.moved(value)
    }

    Binding {
        target: bar
        property: "value"
        value: root.value
        restoreMode: Binding.RestoreBindingOrValue
    }
}
