import QtQuick
import "../../qmlcommon"

// The settings ROWS, with no roof over them — cover columns, volume levelling
// and the library rescan.
//
// TWO ROOFS, ONE PAGE (apps/AGENTS.md → kdeshell): under Hyprland
// `SettingsPanel.qml` is the drawer that slides this in from the titlebar's
// bottom-right corner; in a Plasma session there is no titlebar to slide from
// and main.py puts this same file in a real "Configure player…" dialog
// (`kdeshell.dialog`), where the `+plasma` selector swaps every control below
// for the KDE style's own. Neither roof knows about the other, and the rows
// exist once.
//
// Controlled, not stateful: it owns no setting. `columns` is a binding onto the
// window's value and the controls only emit requests; the window writes them
// back (and persists them), which flows in through the bindings.
Item {
    id: root
    property int columns: 7
    property int minColumns: 2
    property int maxColumns: 12
    property string scanStatus: ""
    property bool scanning: false
    // Foreground tones, handed in already faded by whatever owns this page
    // (docs/DESIGN.md §3.1.1). The dialog hands in the lit ones.
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    // The drawer already insets this page by 12; a dialog does not, so the roof
    // says how much room the rows get from the edge rather than the page
    // guessing which one it is under.
    property int pad: 0

    signal columnsRequested(int n)
    signal rescanRequested()
    signal replayGainRequested(string mode)
    signal rgPreampRequested(real db)

    implicitHeight: col.implicitHeight + 2 * pad
    implicitWidth: 248 + 2 * pad

    Column {
        id: col
        anchors { left: parent.left; right: parent.right; top: parent.top
                  leftMargin: root.pad; rightMargin: root.pad; topMargin: root.pad }
        spacing: 8

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
                        iconName: "list-remove"; iconOnly: true
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
                        iconName: "list-add"; iconOnly: true
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
                height: 24
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "volume levelling"
                    color: root.fgText
                }
                // A dropdown, not a cycler — every pick-one-of-N enum on
                // the desktop opens its menu now (docs/DESIGN.md §7.2).
                SelectButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 90
                    label: Player.replayGain
                    options: ["auto", "track", "album", "off"]
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onPicked: function (x, y, items) {
                        var p = root.mapFromItem(null, x, y);
                        rgMenu.open(p.x, p.y, items);
                    }
                    onChose: function (m) { root.replayGainRequested(m); }
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

        // ---- last.fm ----
        // The whole section is honest about what it can do (docs/DESIGN.md
        // §10): with no API key there is nothing to click, only the one
        // command that puts one there; with an account linked the two
        // switches are what he actually decides. `connect` opens the approval
        // page in his browser and finishes by itself once he says yes — there
        // is no second button to press too early.
        Column {
            width: parent.width
            spacing: 4

            Item {
                width: parent.width
                height: 20
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "last.fm"
                    color: root.fgText
                }
                HeaderButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    visible: Lastfm.hasKeys
                    label: Lastfm.connected ? "disconnect"
                                            : (Lastfm.connecting ? "waiting..." : "connect")
                    iconName: Lastfm.connected ? "network-disconnect" : "network-connect"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    lit: Lastfm.connecting
                    onClicked: {
                        if (Lastfm.connected) Lastfm.disconnectAccount();
                        else if (!Lastfm.connecting) Lastfm.beginConnect();
                    }
                }
            }

            PixelText {
                width: parent.width
                wrapMode: Text.Wrap
                color: root.fgDim
                text: !Lastfm.hasKeys
                      ? "no api key. tools/lastfm-connect.py --keys KEY SECRET"
                      : (Lastfm.connecting
                         ? "approve it in the browser"
                         : (Lastfm.connected
                            ? Lastfm.username + (Lastfm.queued > 0
                                 ? " \u00b7 " + Lastfm.queued + " waiting to send" : "")
                            : "not connected"))
            }

            PixelText {
                width: parent.width
                visible: Lastfm.lastError !== ""
                wrapMode: Text.Wrap
                color: Theme.crit
                text: Lastfm.lastError
            }

            Item {
                width: parent.width
                height: 20
                visible: Lastfm.connected
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "scrobble plays"
                    color: root.fgText
                }
                HeaderButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    label: Lastfm.scrobbling ? "on" : "off"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    lit: Lastfm.scrobbling
                    onClicked: Lastfm.setScrobbling(!Lastfm.scrobbling)
                }
            }

            Item {
                width: parent.width
                height: 20
                visible: Lastfm.connected
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "love favourites"
                    color: root.fgText
                }
                HeaderButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    label: Lastfm.loveOnFavorite ? "on" : "off"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    lit: Lastfm.loveOnFavorite
                    onClicked: Lastfm.setLoveOnFavorite(!Lastfm.loveOnFavorite)
                }
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
                iconName: "view-refresh"
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
            height: Theme.lineHeight + 2  // descender room: one cell + 1px each side
            color: root.fgDim
        }
    }

    // One menu for the page's pickers (§7.3). It fills the page root, so the
    // dropdown clamps against everything this page can see.
    CtxMenu { id: rgMenu; anchors.fill: parent }
}
