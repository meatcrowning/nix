import QtQuick
import "../../qmlcommon"

// player's pseudo-settings drawer, the same idiom as surfer's dark-mode panel:
// the hyprvtb titlebar lives on the window's RIGHT edge and the "st" button is
// bottom-anchored in it, so the drawer docks bottom-right and slides in from
// that edge. A transparent scrim behind it closes it on an outside click.
//
// Controlled, not stateful: it owns no setting. `columns` is a binding onto
// Main's value and the controls only emit requests; Main writes them back
// (and persists them), which flows in through the bindings.
Item {
    id: root
    property bool open: false
    property int columns: 7
    property int minColumns: 2
    property int maxColumns: 12
    property string scanStatus: ""
    property bool scanning: false
    // Foreground tones, handed in already faded by Main (docs/DESIGN.md §3.1.1).
    // The drawer's `Theme.windowBorder` frame does NOT fade: it is the frame
    // that makes this overlay read as a window at all, and Theme already carries
    // a separate `windowBorderInactive` for a genuinely inactive frame.
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    signal closeRequested()
    signal columnsRequested(int n)
    signal rescanRequested()
    signal replayGainRequested(string mode)
    signal rgPreampRequested(real db)

    // Nothing to hit-test while it is fully retracted.
    visible: drawer.slide > 0.001

    MouseArea {
        id: scrim
        anchors.fill: parent
        onClicked: root.closeRequested()
    }

    Motion { id: motion }

    Rectangle {
        id: drawer
        // slide 0 (hidden, fully off the right edge) -> 1 (docked at the edge)
        property real slide: root.open ? 1 : 0
        // The desktop's slide (qmlcommon/Motion.qml), not a local 200ms. This
        // drawer docks to the same edge the hyprvtb titlebar is on and opens
        // next to a window that rolls; at 200 it visibly beat the roll.
        Behavior on slide { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }

        width: Math.min(248, root.width - 16)
        height: Math.min(col.implicitHeight + 24, root.height - 16)
        x: root.width - slide * width
        y: Math.max(8, root.height - height - 8)   // bottom-right, by the "st" button
        color: Theme.bgAlt
        border.width: 1
        border.color: Theme.windowBorder

        // Swallow clicks so they don't reach the scrim behind.
        MouseArea { anchors.fill: parent }

        Column {
            id: col
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
            spacing: 8

            Item {   // header: title + close
                width: parent.width
                height: title.implicitHeight
                PixelText {
                    id: title
                    anchors.left: parent.left
                    text: "settings"
                    color: root.fgAccent
                }
                HeaderButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    label: "×"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: root.closeRequested()
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            // ---- album grid columns: live, in place ----
            Column {
                width: parent.width
                spacing: 4

                Item {
                    width: parent.width
                    height: 20
                    PixelText {
                        id: colLabel
                        anchors.verticalCenter: parent.verticalCenter
                        text: "cover columns"
                        color: root.fgText
                    }
                    Row {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        HeaderButton {
                            label: "-"
                            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                            onClicked: root.columnsRequested(root.columns - 1)
                        }
                        PixelText {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 20
                            horizontalAlignment: Text.AlignHCenter
                            text: root.columns
                            color: root.fgDim
                        }
                        HeaderButton {
                            label: "+"
                            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                            onClicked: root.columnsRequested(root.columns + 1)
                        }
                    }
                }
                Slider {
                    width: parent.width
                    from: root.minColumns
                    to: root.maxColumns
                    step: 1
                    fgAccent: root.fgAccent
                    value: root.columns
                    onMoved: function(v) { root.columnsRequested(v); }
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            // ---- replay gain: library-wide volume levelling ----
            // The mode button cycles; "auto" is album gain within an album and
            // track gain for anything mixed, which is what you actually want
            // without having to think about it.
            Column {
                width: parent.width
                spacing: 4

                Item {
                    width: parent.width
                    height: 20
                    PixelText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "volume levelling"
                        color: root.fgText
                    }
                    HeaderButton {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        label: Player.replayGain
                        fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                        lit: Player.replayGain !== "off"
                        onClicked: {
                            var modes = ["auto", "track", "album", "off"];
                            var i = modes.indexOf(Player.replayGain);
                            root.replayGainRequested(modes[(i + 1) % modes.length]);
                        }
                    }
                }

                PixelText {
                    width: parent.width
                    text: Player.rgStatus
                    wrapMode: Text.Wrap
                    color: root.fgDim
                }

                Item {
                    width: parent.width
                    height: 20
                    visible: Player.replayGain !== "off"
                    PixelText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "preamp"
                        color: root.fgText
                    }
                    PixelText {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: (Player.rgPreamp >= 0 ? "+" : "") + Player.rgPreamp.toFixed(1) + " dB"
                        color: root.fgDim
                    }
                }
                Slider {
                    width: parent.width
                    visible: Player.replayGain !== "off"
                    from: -15
                    to: 15
                    step: 0.5
                    fgAccent: root.fgAccent
                    value: Player.rgPreamp
                    onMoved: function(v) { root.rgPreampRequested(v); }
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            // ---- library ----
            Item {
                width: parent.width
                height: 20
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "library"
                    color: root.fgText
                }
                HeaderButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    label: root.scanning ? "scanning" : "rescan"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    lit: root.scanning
                    onClicked: if (!root.scanning) root.rescanRequested()
                }
            }
            PixelText {
                width: parent.width
                visible: root.scanStatus !== ""
                text: root.scanStatus
                clip: true
                height: Theme.fontSize + 2  // descender room: 16px ink in the 15px line
                color: root.fgDim
            }
        }
    }
}
