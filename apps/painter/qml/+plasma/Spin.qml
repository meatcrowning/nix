import QtQuick
import QtQuick.Controls

// Spin, in a Plasma session: a real SpinBox, drawn by the KDE style — its
// up/down buttons, its editable field, its wheel handling.
//
// Two things the QQC2 SpinBox does not do that ../Spin.qml's callers need, both
// handled here rather than at the call site:
//
//   * IT IS INTEGER-ONLY. painter spins reals (cfg 1.0, denoise, megapixels),
//     so the control works in fixed point — every value scaled by 10^decimals —
//     with textFromValue/valueFromText converting at the edges.
//   * `value` MUST NOT BE ASSIGNED FROM HERE. It is bound to the model
//     (`root.gen.steps` and friends) and writing a bound property destroys the
//     binding, which silently disconnects the box from every later model change
//     — the reasoning is in full in ../Spin.qml's commit(). So the edit is
//     REPORTED (`edited`) and the owner writes it back.
Item {
    id: spin
    property string face: "plasma"
    property real value: 0
    property real from: 0
    property real to: 1000000
    property real step: 1
    property int decimals: 0
    property bool editing: box.activeFocus
    signal edited(real value)

    readonly property real scale: Math.pow(10, decimals)
    function clamp(v) { return Math.max(from, Math.min(to, v)) }

    implicitWidth: box.implicitWidth
    implicitHeight: box.implicitHeight
    height: implicitHeight

    // A NATIVE SPINBOX NEEDS ITS OWN WIDTH. Call sites size ours in pixels
    // (`width: 52`) because a pixel-font box of three digits is that wide; the
    // style's box has stepper buttons inside it and at 52px the number is not
    // visible at all. A `Binding` rather than a plain `width:` because the call
    // site's literal assignment would otherwise win.
    Binding {
        target: spin
        property: "width"
        value: Math.max(box.implicitWidth, 52)
    }

    SpinBox {
        id: box
        anchors.fill: parent
        editable: true
        from: Math.round(spin.from * spin.scale)
        to: Math.round(spin.to * spin.scale)
        stepSize: Math.max(1, Math.round(spin.step * spin.scale))
        value: Math.round(spin.clamp(spin.value) * spin.scale)

        textFromValue: function (v) {
            var real = v / spin.scale
            return spin.decimals > 0 ? real.toFixed(spin.decimals) : String(Math.round(real))
        }
        valueFromText: function (text) {
            var real = parseFloat(String(text).replace(",", "."))
            if (!isFinite(real)) real = spin.value
            return Math.round(spin.clamp(real) * spin.scale)
        }

        // `valueModified` fires for the buttons, the wheel and a committed edit
        // — and NOT for the binding above re-evaluating, which is exactly the
        // distinction that keeps this from feeding the model its own value back.
        onValueModified: spin.edited(value / spin.scale)
    }
}
