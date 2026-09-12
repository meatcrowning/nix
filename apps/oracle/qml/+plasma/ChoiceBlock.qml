import QtQuick
import QtQuick.Controls as QQC

// One candidate on a decision card in a Plasma session: a real KStyle button,
// the same relief as every other button in the window (docs/DESIGN.md §7.6),
// just the size of the block it holds [his, 2026-09-12]. Not flat — the relief
// is what says it can be pressed at all.
//
// Same API as ../ChoiceBlock.qml. `lit` is the style's own CHECKED button, so
// the option he took stays held down among its siblings without a colour of
// ours. `fg`/`fgDim`/`fgFaint` are the BUTTON's text colour and two steps down
// from it, because this content sits on a button surface and not on the
// window's.
//
// The content is laid OVER the button rather than handed to it as
// `contentItem`: a contentItem is measured by the style, and a block of
// wrapping text measured before the button has a width settles one line short
// and never recovers (measured, 51px against the Hyprland face's 67px for the
// same three lines). Here the height is ours, computed the same way in both
// faces. Nothing in the content takes the mouse, so the press still lands on
// the button underneath it.
Item {
    id: root
    property string face: "plasma"
    property bool lit: false
    default property alias blockData: holder.data

    signal clicked()

    readonly property color fg: root.enabled ? Theme.buttonText : Theme.disabledText
    readonly property color fgDim: Qt.rgba(fg.r, fg.g, fg.b, root.enabled ? 0.75 : 0.6)
    readonly property color fgFaint: Qt.rgba(fg.r, fg.g, fg.b, root.enabled ? 0.55 : 0.45)

    readonly property int pad: 10
    implicitHeight: holder.childrenRect.height + pad * 2
    height: implicitHeight

    QQC.Button {
        anchors.fill: parent
        checkable: root.lit
        checked: root.lit
        enabled: root.enabled
        onClicked: root.clicked()
    }

    Item {
        id: holder
        x: root.pad
        y: root.pad
        width: parent.width - root.pad * 2
        height: childrenRect.height
    }
}
