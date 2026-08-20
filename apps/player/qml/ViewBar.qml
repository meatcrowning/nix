import QtQuick
import "../../qmlcommon"

// ViewBar — the view / sort / finder toolbar across the top of the window, in a
// PLASMA session only.
//
// Under Hyprland the view switches (a/p/n), the sort cycler and the `fs` search
// toggle are hyprvtb titlebar cells (Main.qml `tbButtons`); under Plasma there
// is no hyprvtb, so DeskMenuBar.qml brings those cells back as a menubar. His
// call: the three views, the sort control and the finder do NOT belong buried in
// a "view" menu — they are the toolbar every KDE music player keeps directly
// under the menubar. So in this session they come out of the menubar and onto a
// real strip, and the search field is always open on it rather than sliding out
// of a titlebar edge that does not exist here (docs/DESIGN.md §7.6).
//
// Gated on `DeskStyle.plasma` — the same switch PlayBar.qml and the palette use —
// so outside that session the bar is invisible and 0 high and the Hyprland
// window is byte-for-byte what it was: the chrome there is all titlebar.
//
// It owns no search state. The window has ONE search field (Main.qml's
// `searchBar`, the Hyprland slide-out); in this session Main.qml re-parents that
// same field into `searchSlot`, so there is a single source of truth and the
// two chromes cannot drift (the DeskMenuBar "one source, two roofs" rule).
Item {
    id: root

    // Handed in already faded by the window (docs/DESIGN.md §3.1.1).
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    // The window's current page and sort, read-only here.
    property string view: "albums"
    property string sortMode: "orig_year"

    // Where the window docks its single search field in this session.
    property alias searchSlot: searchSlot

    signal viewRequested(string v)
    signal sortRequested()

    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false
    visible: plasma
    height: plasma ? Math.max(24, Theme.lineHeight + 10) : 0

    // The full verb, not the titlebar's two-character "yr"/"ar"/"al" cell — a
    // toolbar has the room a titlebar cell never did (§7.6: the label is the
    // tooltip, the full word).
    readonly property string sortWord: root.sortMode === "orig_year" ? "year"
                                     : (root.sortMode === "artist" ? "artist" : "album")

    Rectangle {
        anchors.fill: parent
        color: Theme.bg

        // The seam under the bar — the same one line the menubar draws below
        // itself, so menubar, toolbar and content read as three bounded fields.
        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: Theme.ctrlBorder
            color: Theme.border
        }

        // ---- the view switches + sort, left-aligned ----------------------
        // HeaderButton is the flat pixel-text control (dim, accent when lit,
        // highlight on hover) — the album-header idiom, §12.1's pixel-font
        // vocabulary. The lit one IS the page you are on (§3.5, §5.4).
        Row {
            id: switches
            anchors { left: parent.left; leftMargin: 8; verticalCenter: parent.verticalCenter }
            spacing: 6

            HeaderButton {
                label: "albums"; lit: root.view === "albums"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: root.viewRequested("albums")
            }
            HeaderButton {
                label: "playlists"; lit: root.view === "playlists"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: root.viewRequested("playlists")
            }
            HeaderButton {
                label: "now playing"; lit: root.view === "now"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: root.viewRequested("now")
            }

            // A hairline divider between the page switches and the sort cycler.
            Rectangle {
                width: Theme.ctrlBorder; height: 14; color: Theme.border
                anchors.verticalCenter: parent.verticalCenter
            }

            HeaderButton {
                label: "sort: " + root.sortWord
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: root.sortRequested()
            }
        }

        // ---- the finder slot, filling the rest of the bar ----------------
        // The window's search field is docked here. It takes every pixel the
        // switches leave, so it shrinks gracefully as the window narrows (the
        // ~480px reference) rather than pushing anything off the edge; a floor
        // keeps it usable, below which the whole strip would need the window
        // wider anyway.
        Item {
            id: searchSlot
            anchors { left: switches.right; leftMargin: 10
                      right: parent.right; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            height: 22
        }
    }
}
