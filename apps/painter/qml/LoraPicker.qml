import QtQuick
import QtQuick.Controls.Basic

// Compatible LoRAs first and one click away.  Incompatible ones are hidden
// behind a count rather than removed, each carrying the reason it did not match
// so a wrong verdict is visible rather than silent -- and can be forced.
Rectangle {
    id: picker
    property bool showAll: false
    signal chose()

    height: 172
    color: Theme.bg
    border.color: Theme.border
    border.width: 1

    function compatCount() {
        var n = 0
        for (var i = 0; i < LoraChoices.rowCount(); i++) {
            if (LoraChoices.data(LoraChoices.index(i, 0), 0x0102)) n++
        }
        return n
    }

    Column {
        anchors.fill: parent
        anchors.margins: 4
        spacing: 3

        Row {
            spacing: 8
            width: parent.width
            PixelText { text: "compatible with this model"; color: Theme.textDim }
            PixelText {
                text: picker.showAll ? "[ hide others ]" : "[ show all ]"
                color: Theme.dim
                MouseArea { anchors.fill: parent; onClicked: picker.showAll = !picker.showAll }
            }
        }

        ListView {
            id: list
            width: parent.width
            height: parent.height - 22
            clip: true
            model: LoraChoices
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: VScroll {}

            delegate: Item {
                width: list.width
                height: (compatible || picker.showAll) ? 20 : 0
                visible: height > 0

                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6
                    width: parent.width

                    PixelText {
                        text: compatible ? "+" : "-"
                        color: compatible ? Theme.ok : Theme.dim
                    }
                    PixelText {
                        text: name
                        color: compatible ? Theme.text : Theme.dim
                        elide: Text.ElideMiddle
                        width: Math.min(implicitWidth, parent.width - 90)
                    }
                    PixelText {
                        visible: !compatible
                        text: "[force]"
                        color: Theme.warn
                        MouseArea {
                            anchors.fill: parent
                            onClicked: App.forceLora(name)
                        }
                    }
                }

                ToolTipArea { anchors.fill: parent; text: reason }

                MouseArea {
                    anchors.fill: parent
                    enabled: compatible
                    onClicked: { Loras.add(name, patchesClip); picker.chose() }
                }
            }
        }
    }
}
