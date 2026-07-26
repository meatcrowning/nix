import QtQuick

// Backend controls and housekeeping.  Deliberately sparse: everything that
// affects an image lives in the main panel, and everything here is about the
// process behind it.
Item {
    id: drawer
    signal closed()

    MouseArea {
        anchors.fill: parent
        onClicked: drawer.closed()
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(460, parent.width - 60)
        height: col.implicitHeight + 24
        color: Theme.bgAlt
        border.color: Theme.accent
        border.width: 1
        radius: 2

        MouseArea { anchors.fill: parent }   // swallow clicks inside

        Column {
            id: col
            anchors.centerIn: parent
            width: parent.width - 24
            spacing: 8

            PixelText { text: "SETTINGS"; color: Theme.accent }
            Rectangle { width: parent.width; height: 1; color: Theme.border }

            PixelText { text: "backend: " + App.status; color: Theme.textDim }
            PixelText {
                text: "logs: journalctl --user -u comfy-painter -f"
                color: Theme.dim
                width: parent.width
                elide: Text.ElideRight
            }

            Row {
                spacing: 12
                PixelText {
                    text: "[ start ]"
                    color: Theme.ok
                    MouseArea { anchors.fill: parent; onClicked: App.startBackend() }
                }
                PixelText {
                    text: "[ stop ]"
                    color: Theme.crit
                    MouseArea { anchors.fill: parent; onClicked: App.stopBackend() }
                }
                PixelText {
                    text: "[ unload models ]"
                    color: Theme.warn
                    MouseArea { anchors.fill: parent; onClicked: App.unloadModels() }
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            Row {
                spacing: 12
                PixelText {
                    text: "[ rescan models ]"
                    color: Theme.accent
                    MouseArea { anchors.fill: parent; onClicked: App.rescan() }
                }
                PixelText { text: Models.count + " known"; color: Theme.textDim }
            }

            PixelText {
                text: "models: /home/lam/models"
                color: Theme.dim
            }
            PixelText {
                text: "overrides: ~/.local/state/painter/overrides.json"
                color: Theme.dim
                width: parent.width
                elide: Text.ElideRight
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }
            PixelText {
                text: "[ close ]"
                color: Theme.text
                MouseArea { anchors.fill: parent; onClicked: drawer.closed() }
            }
        }
    }
}
