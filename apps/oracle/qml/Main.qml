import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import "../../qmlcommon"

// oracle's window: a model selector across the top, a reply area that fills the
// middle, and a prompt box along the bottom. Every control is drawn here in the
// desktop's pixel idiom (docs/DESIGN.md) — the compositor draws the titlebar
// (§12), so there is no chrome strip.
//
// Deliberately one file: oracle is minimal by design (a model list from
// /api/tags, one streamed turn to /api/chat) and has nothing that earns a second
// component. The model dropdown is inline rather than a shared CtxMenu, so this
// window pulls in nothing but the theme, PixelText and the Kinetic views.
Window {
    id: win
    width: 620
    height: 720
    visible: true
    color: Theme.bg
    title: "oracle"

    property string model: ""
    property string replyText: ""
    property string thinkText: ""
    property string status: ""

    // The pixel font is monospace; one measurement gives the column advance.
    TextMetrics {
        id: metrics
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        text: "MMMMMMMMMM"
    }
    readonly property real cellW: metrics.width > 0 ? metrics.width / 10
                                                    : Math.round(0.533 * Theme.fontSize)

    Motion { id: motion }

    Component.onCompleted: Titlebar.setFooter(ollamaHost.replace(/^https?:\/\//, ""))

    // Keep a model selected: default to the first the daemon reports, and never
    // point at a model that has gone away.
    Connections {
        target: Ollama
        function onModelsChanged() {
            if (win.model === "" || Ollama.models.indexOf(win.model) < 0)
                win.model = Ollama.models.length > 0 ? Ollama.models[0] : "";
        }
        function onReplyStarted() { win.replyText = ""; win.thinkText = ""; win.status = ""; }
        function onReplyChunk(piece) { win.replyText += piece; }
        function onReplyThinking(piece) { win.thinkText += piece; }
        function onReplyDone() { win.status = ""; }
        function onReplyError(reason) { win.status = "error: " + reason; }
        function onModelsError(reason) { win.status = "no models: " + reason; }
    }

    // The backend controls (server up/down, loaded model, start/stop, unload)
    // report through the same status line the model list uses, and refill the
    // model list the moment the daemon comes back up.
    Connections {
        target: Backend
        function onNote(msg) { win.status = msg; }
        function onStatusChanged() {
            if (Backend.serverUp && Ollama.models.length === 0)
                Ollama.refreshModels();
        }
    }

    function send() {
        var p = input.text.trim();
        if (p === "" || win.model === "" || Ollama.busy)
            return;
        Ollama.send(win.model, p);
        input.clear();
    }

    // ---------------------------------------------------------------- top row
    Item {
        id: top
        anchors { top: parent.top; left: parent.left; right: parent.right
                  margins: 10 }
        height: 28

        PixelText {
            id: modelLabel
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: "model"
            color: Theme.textDim
        }

        // The selector: a boxed control showing the current model, which opens
        // an inline list of the daemon's models under itself (docs/DESIGN.md
        // §7.2 — no combo boxes on this desktop).
        Rectangle {
            id: picker
            anchors { left: modelLabel.right; leftMargin: 10
                      right: parent.right
                      verticalCenter: parent.verticalCenter }
            height: 24
            color: pickerMouse.containsMouse ? Theme.highlight : Theme.bgAlt
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border

            property bool open: false

            PixelText {
                anchors { left: parent.left; leftMargin: 6
                          right: caret.left; rightMargin: 6
                          verticalCenter: parent.verticalCenter }
                elide: Text.ElideRight
                text: win.model !== "" ? win.model
                                       : (Ollama.models.length > 0 ? "pick a model"
                                                                   : "no models found")
                color: win.model !== "" ? Theme.text : Theme.textDim
            }
            PixelText {
                id: caret
                anchors { right: parent.right; rightMargin: 6
                          verticalCenter: parent.verticalCenter }
                text: picker.open ? "^" : "v"
                color: Theme.textDim
            }

            MouseArea {
                id: pickerMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: picker.open = !picker.open
            }
        }
    }

    // -------------------------------------------------- server / backend row
    // Observed state on the left (up/down + the loaded model, polled from
    // /api/ps, docs/DESIGN.md §10.6 — never claimed from a click), the two
    // controls on the right: unload the loaded model, and start/stop the daemon.
    Item {
        id: serverRow
        anchors { top: top.bottom; topMargin: 8
                  left: parent.left; right: parent.right; margins: 10 }
        height: 22

        PixelText {
            id: serverLabel
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: "server"
            color: Theme.textDim
        }
        PixelText {
            anchors { left: serverLabel.right; leftMargin: 10
                      right: unloadBtn.left; rightMargin: 10
                      verticalCenter: parent.verticalCenter }
            elide: Text.ElideRight
            text: Backend.serverUp
                  ? (Backend.loadedModels.length > 0
                     ? "up · " + Backend.loadedModels.join(", ")
                     : "up · idle")
                  : "down"
            color: Backend.serverUp
                   ? (Backend.loadedModels.length > 0 ? Theme.ok : Theme.textDim)
                   : Theme.crit
        }

        // Unload — enabled only when a model is actually loaded (§10.2: a
        // control with no reading is dimmed and refuses, not silently inert).
        Rectangle {
            id: unloadBtn
            anchors { right: powerBtn.left; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            width: 64
            height: 22
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            readonly property bool armed: Backend.loadedModels.length > 0
            color: unloadMouse.containsMouse && armed ? Theme.highlight : Theme.bg
            PixelText {
                anchors.centerIn: parent
                text: "unload"
                color: unloadBtn.armed ? Theme.accent : Theme.dim
            }
            MouseArea {
                id: unloadMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: unloadBtn.armed ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: if (unloadBtn.armed) Backend.unloadModels()
            }
        }

        // Start / stop — reflects the OBSERVED server state; disabled while a
        // start/stop is in flight (the askpass dialog may be up).
        Rectangle {
            id: powerBtn
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            width: 84
            height: 22
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            color: powerMouse.containsMouse && !Backend.busy ? Theme.highlight : Theme.bg
            PixelText {
                anchors.centerIn: parent
                text: Backend.busy ? "…"
                      : (Backend.serverUp ? "stop server" : "start server")
                color: Backend.busy ? Theme.textDim
                       : (Backend.serverUp ? Theme.warn : Theme.accent)
            }
            MouseArea {
                id: powerMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Backend.busy ? Qt.ArrowCursor : Qt.PointingHandCursor
                onClicked: {
                    if (Backend.busy) return;
                    if (Backend.serverUp) Backend.stopServer();
                    else Backend.startServer();
                }
            }
        }
    }

    // The dropdown floats over the reply area, overlaying the picker exactly.
    // It anchors to `top` (a sibling) and takes the picker's width rather than
    // anchoring to `picker` itself — the picker is `top`'s child, a nephew of
    // this dropdown, and QML silently drops an anchor to a non-sibling (the
    // dropdown then had width 0 and never showed). picker.right == top.right, so
    // right:top.right + width:picker.width lands it on the same span.
    Rectangle {
        id: dropdown
        visible: picker.open && Ollama.models.length > 0
        anchors { top: top.bottom; topMargin: -6; right: top.right }
        width: picker.width
        height: Math.min(Ollama.models.length * 22 + 2, 240)
        z: 50
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border

        KineticListView {
            id: modelList
            anchors { fill: parent; margins: 1 }
            clip: true
            model: Ollama.models
            delegate: Rectangle {
                width: modelList.width
                height: 22
                color: rowMouse.containsMouse ? Theme.highlight : "transparent"
                PixelText {
                    anchors { left: parent.left; leftMargin: 6
                              right: parent.right; rightMargin: 6
                              verticalCenter: parent.verticalCenter }
                    elide: Text.ElideRight
                    text: modelData
                    color: modelData === win.model ? Theme.accent : Theme.text
                }
                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { win.model = modelData; picker.open = false; }
                }
            }
            ScrollBar.vertical: VScroll {}
        }
    }

    // A click anywhere else closes the dropdown.
    MouseArea {
        anchors.fill: parent
        z: 40
        visible: picker.open
        onClicked: picker.open = false
    }

    // --------------------------------------------------------- the reply area
    Rectangle {
        id: replyBox
        anchors { top: serverRow.bottom; topMargin: 10
                  left: parent.left; right: parent.right
                  bottom: promptBox.top
                  leftMargin: 10; rightMargin: 10; bottomMargin: 10 }
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border

        KineticFlickable {
            id: replyFlick
            anchors { fill: parent; margins: 8; rightMargin: replyScroll.barW + 4 }
            contentWidth: width
            contentHeight: reply.height
            clip: true

            PixelText {
                id: reply
                width: replyFlick.width
                wrapMode: Text.Wrap
                // The answer once it starts; the reasoning (dimmed) while a
                // thinking model is still reasoning; an error; else a hint.
                text: win.replyText !== "" ? win.replyText
                      : (win.thinkText !== "" ? win.thinkText
                         : (win.status !== "" ? win.status
                            : (Ollama.busy ? "…" : "ask the model something below.")))
                color: win.replyText !== "" ? Theme.text
                       : (win.thinkText !== "" ? Theme.textDim
                          : (win.status !== "" ? Theme.crit : Theme.textDim))
            }

            // Follow the stream to the bottom as it grows.
            onContentHeightChanged: if (Ollama.busy)
                contentY = Math.max(0, contentHeight - height)

            ScrollBar.vertical: VScroll { id: replyScroll }
        }
    }

    // --------------------------------------------------------- the prompt box
    Rectangle {
        id: promptBox
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                  leftMargin: 10; rightMargin: 10; bottomMargin: 10 }
        height: Math.max(48, Math.min(160, input.implicitHeight + 16))
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: input.activeFocus ? Theme.accent : Theme.border

        KineticFlickable {
            id: inputFlick
            anchors { top: parent.top; bottom: parent.bottom
                      left: parent.left; right: sendBtn.left
                      margins: 8 }
            contentWidth: width
            contentHeight: input.implicitHeight
            clip: true

            TextEdit {
                id: input
                width: inputFlick.width
                font: Theme.editorFont
                color: Theme.text
                selectionColor: Theme.accent
                selectedTextColor: Theme.bg
                wrapMode: TextEdit.Wrap
                persistentSelection: true
                focus: true

                // Ctrl+Return sends; a bare Return keeps typing a paragraph.
                Keys.onPressed: function (e) {
                    if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                        && (e.modifiers & Qt.ControlModifier)) {
                        win.send();
                        e.accepted = true;
                    }
                }

                PixelText {
                    anchors { left: parent.left; verticalCenter: parent.top
                              verticalCenterOffset: parent.implicitHeight / 2 }
                    visible: input.text === "" && !input.activeFocus
                    text: "ask the model…  (Ctrl+Enter to send)"
                    color: Theme.textDim
                }
            }
        }

        Rectangle {
            id: sendBtn
            anchors { right: parent.right; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            width: 56
            height: 24
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            readonly property bool armed: input.text.trim() !== "" && win.model !== ""
            color: sendMouse.containsMouse && (armed || Ollama.busy)
                   ? Theme.highlight : Theme.bg
            PixelText {
                anchors.centerIn: parent
                text: Ollama.busy ? "stop" : "send"
                color: Ollama.busy ? Theme.warn
                       : (sendBtn.armed ? Theme.accent : Theme.dim)
            }
            MouseArea {
                id: sendMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: (sendBtn.armed || Ollama.busy)
                             ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: {
                    if (Ollama.busy) Ollama.cancel();
                    else win.send();
                }
            }
        }
    }
}
