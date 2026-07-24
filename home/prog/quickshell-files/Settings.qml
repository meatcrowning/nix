import QtQuick
import Quickshell
import Quickshell.Io

// The Settings program — its own bespoke Quickshell instance, run as a daemon
// from the same config directory as the panel:
//
//     qs -d -n -p ~/.config/quickshell/Settings.qml
//
// Because it lives in that directory it reuses the panel's singletons — Theme
// (so it recolours with the wallpaper), PixelText, and SettingsStore (the
// on-disk JSON model) — with zero duplication. It stays resident and shows/
// hides via IPC so toggling is instant:
//
//     qs -p ~/.config/quickshell/Settings.qml ipc call settings toggle
//
// A real FloatingWindow, so the hyprvtb plugin gives it the same vertical
// titlebar / drag / resize as every other window. The INNER titlebar — the
// horizontal strip of page tabs at the top of the content — is ours, and each
// tab is one of the settings pages.
Scope {
    id: root

    // window visibility, driven by IPC (kept resident between shows)
    property bool shown: true

    // the page tabs, in order. `src` is a sibling QML file loaded on demand.
    readonly property var pages: [
        { key: "appearance", label: "appearance", src: "SetPgAppearance.qml" },
        { key: "panel",      label: "panel",      src: "SetPgPanel.qml" },
        { key: "audio",      label: "audio",      src: "SetPgAudio.qml" },
        { key: "notifs",     label: "notifs",     src: "SetPgNotifs.qml" },
        { key: "apps",       label: "apps",       src: "SetPgApps.qml" },
        { key: "session",    label: "session",    src: "SetPgSession.qml" },
        { key: "system",     label: "system",     src: "SetPgSystem.qml" },
        { key: "display",    label: "display",    src: "SetPgDisplay.qml" }
    ]
    property string current: "appearance"
    function srcFor(k) {
        for (const p of pages) if (p.key === k) return p.src;
        return pages[0].src;
    }

    IpcHandler {
        target: "settings"
        function toggle(): void { root.shown = !root.shown; }
        function show(): void { root.shown = true; }
        function hide(): void { root.shown = false; }
    }

    FloatingWindow {
        id: win
        title: "settings"
        implicitWidth: 720
        implicitHeight: 580
        minimumSize: Qt.size(520, 380)
        visible: root.shown
        color: Theme.bg

        // keep the process resident when the titlebar's close is used — just
        // hide, so the next IPC show() is instant
        onClosed: root.shown = false

        // capture Escape to close; refocus the content when (re)shown
        onVisibleChanged: if (visible) content.forceActiveFocus()

        Item {
            id: content
            anchors.fill: parent
            focus: true
            Keys.onEscapePressed: root.shown = false

            // ---- inner titlebar: the page tabs ----
            Rectangle {
                id: tabbar
                anchors { top: parent.top; left: parent.left; right: parent.right }
                height: 32
                color: Theme.bgAlt
                // seam under the titlebar
                Rectangle {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                    height: 1
                    color: Theme.border
                }

                // tabs scroll horizontally if the window is made very narrow
                Flickable {
                    anchors.fill: parent
                    contentWidth: tabRow.width
                    contentHeight: height
                    flickableDirection: Flickable.HorizontalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    clip: true

                    Row {
                        id: tabRow
                        height: parent.height

                        Repeater {
                            model: root.pages
                            Rectangle {
                                required property var modelData
                                readonly property bool active: root.current === modelData.key
                                height: tabbar.height
                                width: Math.max(72, tabT.implicitWidth + 26)
                                color: active ? Theme.bg : (tabMa.containsMouse ? Theme.highlight : "transparent")

                                // active tab marked with an accent underline
                                Rectangle {
                                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                                    height: 2
                                    visible: parent.active
                                    color: Theme.accent
                                }
                                PixelText {
                                    id: tabT
                                    anchors.centerIn: parent
                                    text: parent.modelData.label
                                    color: parent.active ? Theme.accent
                                         : (tabMa.containsMouse ? Theme.text : Theme.textDim)
                                }
                                MouseArea {
                                    id: tabMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.current = parent.modelData.key
                                }
                            }
                        }
                    }
                }
            }

            // ---- page body: scrollable ----
            Flickable {
                id: scroller
                anchors { top: tabbar.bottom; left: parent.left; right: parent.right; bottom: footer.top }
                anchors.margins: 16
                contentWidth: width
                contentHeight: pageLoader.item ? pageLoader.item.implicitHeight : 0
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                Loader {
                    id: pageLoader
                    width: scroller.width
                    source: root.srcFor(root.current)
                }
            }

            // thin scroll indicator on the right edge of the body
            Rectangle {
                visible: scroller.contentHeight > scroller.height
                width: 3
                radius: 0
                color: Theme.dim
                anchors.right: scroller.right
                anchors.rightMargin: -10
                y: scroller.y + (scroller.contentHeight > 0 ? scroller.contentY / scroller.contentHeight * scroller.height : 0)
                height: scroller.contentHeight > 0 ? Math.max(24, scroller.height * scroller.height / scroller.contentHeight) : 0
            }

            // ---- footer: autosave hint + restore defaults ----
            Rectangle {
                id: footer
                anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
                height: 34
                color: Theme.bgAlt
                Rectangle {
                    anchors { left: parent.left; right: parent.right; top: parent.top }
                    height: 1
                    color: Theme.border
                }
                PixelText {
                    anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                    text: "changes save automatically"
                    color: Theme.textDim
                }
                Row {
                    anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                    spacing: 6
                    BrowserButton {
                        label: "reload"
                        onClicked: SettingsStore.revert()
                    }
                    BrowserButton {
                        label: "restore defaults"
                        danger: true
                        onClicked: confirmReset.open()
                    }
                }
            }

            // confirm before wiping every setting (reuses the file browser's
            // confirm dialog)
            BrowserConfirm {
                id: confirmReset
                text: "restore all settings to defaults?"
                onConfirmed: SettingsStore.restoreDefaults()
            }
        }
    }
}
