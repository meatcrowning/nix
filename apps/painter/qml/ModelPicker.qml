import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// Choosing a model is the only decision required: the line under each name is
// what painter worked out to go with it.  Anything it could not place sinks to
// the bottom with a family dropdown attached.
Panel {
    id: panel
    title: "model"
    // Collapsed, the badge is the only thing left saying what is selected, so
    // it carries the name rather than just the count.
    badge: panel.collapsed ? App.selectedName : (Models.count + " found")

    Rectangle {
        width: parent.width
        height: 190
        color: Theme.bg
        border.color: Theme.border
        border.width: 1

        KineticListView {
            id: list
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            model: Models
            currentIndex: App.selectedIndex
            highlightMoveDuration: 0
            ScrollBar.vertical: VScroll {}

            delegate: Rectangle {
                width: list.width
                height: known ? 34 : 52
                color: index === App.selectedIndex ? Theme.highlight
                     : (hover.containsMouse ? Qt.darker(Theme.highlight, 1.4) : "transparent")

                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 6
                    width: parent.width - 12
                    spacing: 1

                    Row {
                        spacing: 6
                        width: parent.width
                        PixelText {
                            text: name
                            color: known ? (index === App.selectedIndex ? Theme.accent : Theme.text)
                                         : Theme.warn
                            elide: Text.ElideMiddle
                            width: Math.min(implicitWidth, parent.width - 130)
                        }
                        PixelText { text: label; color: Theme.dim }
                        PixelText { text: quant; color: Theme.dim; visible: quant !== "" }
                        PixelText { text: overridden ? "(set)" : ""; color: Theme.info }
                    }
                    PixelText {
                        text: problem !== "" ? problem : pairing
                        color: problem !== "" ? Theme.crit : Theme.textDim
                        width: parent.width
                        elide: Text.ElideRight
                    }
                    // Unrecognised files get a way to be classified by hand.
                    Row {
                        visible: !known
                        spacing: 6
                        PixelText { text: "family:"; color: Theme.textDim }
                        Picker {
                            width: 150
                            options: App.familyIds()
                            value: family
                            onPicked: function (v) { App.assignFamily(index, v) }
                        }
                    }
                }

                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: App.selectModel(index)
                }
            }
        }
    }

    // The resolved pairing, with a way to override either half.
    PairingRow { width: parent.width }
}
