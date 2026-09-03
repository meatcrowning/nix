import QtQuick
import QtQuick.Controls

// Plasma's native SpinBox stores an `int`, so it cannot display or return the
// 53-bit seeds Comfy uses. A styled TextField is the native KDE control that
// preserves the number; the three seed-policy buttons supply the rgthree
// actions that matter here.
Item {
    id: seed
    property real value: -1
    signal edited(real value)

    implicitWidth: 180
    implicitHeight: box.implicitHeight
    height: implicitHeight

    function fmt(v) { return String(Math.round(Number(v))) }
    function showValue(v) {
        syncing = true
        box.text = fmt(v)
        syncing = false
    }
    function commit() {
        var n = Number(box.text)
        if (!Number.isFinite(n)) {
            showValue(seed.value)
            return
        }
        n = Math.max(-3, Math.min(9007199254740992, Math.round(n)))
        showValue(n)
        if (n !== seed.value) seed.edited(n)
    }

    property bool syncing: false
    onValueChanged: if (!box.activeFocus) showValue(value)
    Component.onCompleted: showValue(value)

    TextField {
        id: box
        anchors.fill: parent
        objectName: "seedTextInput"
        selectByMouse: true
        persistentSelection: true
        validator: RegularExpressionValidator { regularExpression: /^-?[0-9]*$/ }
        onEditingFinished: seed.commit()

        MouseArea {
            anchors.fill: parent
            z: 10
            acceptedButtons: Qt.RightButton
            onPressed: function (m) {
                box.forceActiveFocus()
                var hasSel = box.selectionEnd > box.selectionStart
                var items = [
                    { label: "cut", enabled: hasSel, trigger: () => box.cut() },
                    { label: "copy", enabled: hasSel, trigger: () => box.copy() },
                    { label: "paste", trigger: () => { box.paste(); seed.commit() } },
                    { label: "select all", trigger: () => box.selectAll() }
                ]
                var p = mapToItem(null, m.x, m.y)
                root.ctxMenu.open(p.x, p.y, items)
            }
        }
    }
}
