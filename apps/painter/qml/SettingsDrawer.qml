import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// Backend controls and housekeeping.  Deliberately sparse: everything that
// affects an image lives in the main panel, and everything here is about the
// process behind it.
//
// It is a DRAWER, not a centred modal. The hyprvtb titlebar runs down the
// window's right edge and the "st" cell is bottom-anchored in it, so this docks
// bottom-right and slides in from that edge — secondary UI slides out from the
// button that owns it (docs/DESIGN.md §7.4), and nothing on this desktop appears
// centred without moving (§6.2). Same construction as player's SettingsPanel.
//
// The backend controls report the UNIT'S state, not the last click's intent:
// `[ start ]` is dead while it is already running and `[ stop ]` while it is
// not, and both refuse rather than pretending (§10). App.stopBackend() now
// checks systemctl's exit code before it claims anything.
Item {

    // The desktop's one slide duration + curve (docs/DESIGN.md 6.2):
    // hyprvtb's roll, scaled by reduceMotion/animSpeed. NEVER a literal.
    Motion { id: motion }
    id: drawer
    property bool open: false
    signal closed()

    // AS A DIALOG, under Plasma. A KDE program's settings are a window with a
    // title bar and a Close button (Settings → Configure painter…), not a panel
    // that slides out of a titlebar cell that is not there — so in that session
    // the same content fills a QDialog instead (pylib/kdeshell.py `dialog`,
    // qml/SettingsPage.qml). What changes is only the packaging: no slide, no
    // scrim, no card inset and no title row, because the dialog supplies all
    // four.
    property bool asDialog: false

    // Nothing to hit-test while it is fully retracted.
    visible: drawer.asDialog || card.slide > 0.001

    MouseArea {
        id: scrim
        anchors.fill: parent
        visible: !drawer.asDialog
        onClicked: drawer.closed()
    }

    Rectangle {
        id: card
        // slide 0 (hidden, fully off the right edge) -> 1 (docked at the edge)
        property real slide: drawer.open ? 1 : 0
        Behavior on slide { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }

        width: drawer.asDialog ? drawer.width : Math.min(420, drawer.width - 16)
        height: drawer.asDialog ? drawer.height
                                : Math.min(col.implicitHeight + 24, drawer.height - 16)
        x: drawer.asDialog ? 0 : drawer.width - slide * width
        // bottom-right, by the "st" cell
        y: drawer.asDialog ? 0 : Math.max(8, drawer.height - height - 8)
        color: drawer.asDialog ? "transparent" : Theme.bgAlt
        border.color: Theme.windowBorder
        border.width: drawer.asDialog ? 0 : Theme.ctrlBorder

        MouseArea { anchors.fill: parent }   // swallow clicks inside

        Column {
            id: col
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
            spacing: 8

            Item {
                width: parent.width
                visible: !drawer.asDialog
                height: visible ? title.implicitHeight : 0
                PixelText {
                    id: title
                    anchors.left: parent.left
                    text: "settings"
                    color: root.fgAccent
                }
                TextButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    label: "x"
                    tone: Theme.textDim
                    winActive: root.winActive
                    onClicked: drawer.closed()
                }
            }

            Rectangle {
                width: parent.width
                visible: !drawer.asDialog
                height: visible ? 1 : 0
                color: Theme.border
            }

            PixelText {
                text: "backend: " + App.status
                color: Theme.textDim
                width: parent.width
                elide: Text.ElideRight
            }
            PixelText {
                text: "unit: " + App.unitState
                color: App.backendRunning ? Theme.ok : Theme.dim
            }
            PixelText {
                text: "logs: journalctl --user -u comfy-painter -f"
                color: Theme.dim
                width: parent.width
                elide: Text.ElideRight
            }

            // Live comfy.py websocket activity (queued/started/running/finished/
            // error) — App.logLines, newest last, kept scrolled to the bottom
            // unless he has scrolled up to read something older.
            Rectangle {
                width: parent.width
                height: 96
                color: Theme.bg
                border.color: Theme.border
                border.width: Theme.ctrlBorder
                clip: true

                KineticListView {
                    id: logView
                    anchors.fill: parent
                    anchors.margins: 4
                    clip: true
                    model: App.logLines
                    spacing: 1
                    ScrollBar.vertical: VScroll { id: logScroll }
                    delegate: PixelText {
                        width: logView.width - logScroll.barW
                        text: modelData
                        color: Theme.dim
                        elide: Text.ElideRight
                    }
                    // Only auto-follow when already at (or near) the bottom, so
                    // scrolling up to read an older line is not yanked away by
                    // the next event.
                    property bool atBottom: atYEnd
                    onCountChanged: if (atBottom) positionViewAtEnd()
                }
            }

            Row {
                spacing: 6
                TextButton {
                    label: "[ start ]"
                    tone: Theme.ok
                    enabled: !App.backendRunning
                    winActive: root.winActive
                    onClicked: App.startBackend()
                }
                TextButton {
                    label: "[ stop ]"
                    tone: Theme.crit
                    enabled: App.backendRunning
                    winActive: root.winActive
                    onClicked: App.stopBackend()
                }
                TextButton {
                    label: "[ unload models ]"
                    tone: Theme.warn
                    // /free at a backend that is not there is a silent no-op.
                    enabled: App.ready
                    winActive: root.winActive
                    onClicked: App.unloadModels()
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            Row {
                spacing: 6
                TextButton {
                    label: "[ rescan models ]"
                    winActive: root.winActive
                    onClicked: App.rescan()
                }
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: Models.count + " known"
                    color: Theme.textDim
                }
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
        }
    }
}
