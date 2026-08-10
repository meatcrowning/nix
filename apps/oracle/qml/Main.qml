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
    property string status: ""
    // The conversation is a persistent LOG, not one turn swapped out under the
    // last: every send appends a `you` row and an assistant row to `chatLog`,
    // prior turns stay in place and scrolled back, readable (docs/DESIGN.md §14 —
    // nothing scrubs history from view). `activeIndex` is the assistant row the
    // in-flight stream is writing into.
    property int activeIndex: -1
    // The result of the last start/stop/unload — its OWN readout (docs/DESIGN.md
    // §10.6), never folded into the observed up/down above and never routed to
    // the reply area, where a finished answer would hide whether the stop worked.
    property string serverNote: ""

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

    // The whole conversation, one row per turn. Roles: `isUser` (bool), `who`
    // (the caption — "you" or the answering model), `body`, `thinking`,
    // `thinkingActive` (the reasoning is streaming right now), `streaming` (the
    // answer is), `isError`.
    ListModel { id: chatLog }

    Component.onCompleted: Titlebar.setFooter(ollamaHost.replace(/^https?:\/\//, ""))

    // Keep a model selected: default to the first the daemon reports, and never
    // point at a model that has gone away.
    Connections {
        target: Ollama
        function onModelsChanged() {
            if (win.model === "" || Ollama.models.indexOf(win.model) < 0)
                win.model = Ollama.models.length > 0 ? Ollama.models[0] : "";
        }
        // The turns are appended by send() before the stream opens; these deltas
        // only ever write into the active assistant row. The first content delta
        // is also what SETTLES the thinking heading from "thinking…" to "thinking".
        function onReplyChunk(piece) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "body", cur.body + piece);
            if (cur.thinkingActive)
                chatLog.setProperty(win.activeIndex, "thinkingActive", false);
        }
        function onReplyThinking(piece) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "thinking", cur.thinking + piece);
            if (!cur.thinkingActive)
                chatLog.setProperty(win.activeIndex, "thinkingActive", true);
        }
        // The live reasoning-token count, written into the active row so the
        // collapsed heading shows it climbing while the model thinks.
        function onReplyThinkTokens(n) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "thinkTokens", n);
        }
        function onReplyDone() {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "streaming", false);
            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
        }
        function onReplyError(reason) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "body", "error: " + reason);
            chatLog.setProperty(win.activeIndex, "isError", true);
            chatLog.setProperty(win.activeIndex, "streaming", false);
            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
        }
        function onModelsError(reason) { win.status = "no models: " + reason; }
    }

    // The backend controls (server up/down, loaded model, start/stop, unload)
    // report through the same status line the model list uses, and refill the
    // model list the moment the daemon comes back up.
    Connections {
        target: Backend
        function onNote(msg) { win.serverNote = msg; }
        function onStatusChanged() {
            if (Backend.serverUp && Ollama.models.length === 0)
                Ollama.refreshModels();
        }
    }

    function send() {
        var p = input.text.trim();
        if (p === "" || win.model === "" || Ollama.busy)
            return;
        win.status = "";
        // Append the pair now, then stream into the assistant row. Prior turns
        // are left untouched — the log grows downward (docs/DESIGN.md §14).
        chatLog.append({ isUser: true, who: "you", body: p,
                         thinking: "", thinkingActive: false,
                         streaming: false, isError: false });
        chatLog.append({ isUser: false, who: win.model, body: "",
                         thinking: "", thinkingActive: false, thinkTokens: 0,
                         streaming: true, isError: false });
        win.activeIndex = chatLog.count - 1;
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

    // The last server-action result, drawn right under its controls so it is
    // seen wherever the reply area happens to be (docs/DESIGN.md §10 — a failed
    // or in-flight stop must be visible, not assumed). Collapsed until an action
    // has spoken; "…" while one is in flight (textDim), crit on failure.
    PixelText {
        id: serverNoteText
        anchors { top: serverRow.bottom; left: parent.left; right: parent.right
                  leftMargin: 10; rightMargin: 10
                  topMargin: win.serverNote !== "" ? 4 : 0 }
        height: win.serverNote !== "" ? Theme.lineHeight : 0
        visible: height > 0
        clip: true
        elide: Text.ElideRight
        text: win.serverNote
        color: win.serverNote.indexOf("failed") >= 0 ? Theme.crit
               : (Backend.busy ? Theme.textDim : Theme.ok)
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
        anchors { top: serverNoteText.bottom; topMargin: 10
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
            contentHeight: replyCol.height
            clip: true

            Column {
                id: replyCol
                width: replyFlick.width
                spacing: 12

                // The opening hint / model-list error, shown only on an empty log.
                PixelText {
                    width: parent.width
                    visible: chatLog.count === 0
                    wrapMode: Text.Wrap
                    text: win.status !== "" ? win.status
                                            : "ask the model something below."
                    color: win.status !== "" ? Theme.crit : Theme.textDim
                }

                // One row per turn — user prompts and model answers alike stay in
                // the log as it grows (docs/DESIGN.md §14).
                Repeater {
                    model: chatLog
                    delegate: Item {
                        id: turn
                        width: replyCol.width
                        height: turnCol.height

                        // The disclosure's open/closed is VIEW state, per row, and
                        // it defaults CLOSED: reasoning is collapsed until he opens
                        // it (docs/DESIGN.md §9.1 — subordinated, never in his way).
                        property bool userSet: false
                        property bool userOpen: false

                        Column {
                            id: turnCol
                            width: parent.width
                            spacing: 4

                            PixelText {
                                text: who
                                color: Theme.textDim
                            }

                            // The reasoning, a COLLAPSIBLE disclosure that starts
                            // folded. Its heading reports progress: "thinking…"
                            // (one step brighter) while the reasoning streams, and
                            // settles to "thinking" (textDim) once the answer
                            // starts. Subordinated per docs/DESIGN.md §9.1 —
                            // indented, a `border` hairline at the indent, text one
                            // step dim, never accent — revealed by §6.2's clipped
                            // growth from under the toggle.
                            Item {
                                id: think
                                width: parent.width
                                visible: !isUser && thinking !== ""
                                height: visible ? thinkToggle.height + thinkReveal.height : 0

                                readonly property bool expanded: turn.userSet ? turn.userOpen
                                                                              : false

                                Item {
                                    id: thinkToggle
                                    width: parent.width
                                    height: Theme.lineHeight
                                    // The ellipsis cycles 0→1→2→3 dots while the
                                    // reasoning streams, so the heading reads as
                                    // alive even between token deltas. One roll
                                    // beat per dot (§6.2) — no fresh literal, and
                                    // reduceMotion collapses it to a static "…".
                                    property int dotPhase: 0
                                    readonly property string dots:
                                        motion.reduceMotion ? "…" : "...".substring(0, dotPhase)
                                    Timer {
                                        interval: motion.ms(motion.slideMs)
                                        running: thinkingActive && !motion.reduceMotion
                                        repeat: true
                                        onTriggered: thinkToggle.dotPhase = (thinkToggle.dotPhase + 1) % 4
                                    }
                                    Row {
                                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                        spacing: 6
                                        PixelText { text: think.expanded ? "-" : "+"; color: Theme.textDim }
                                        PixelText {
                                            text: "thinking"
                                            color: thinkingActive ? Theme.text : Theme.textDim
                                        }
                                        // Live token count + animated ellipsis while
                                        // active; both gone once the answer starts
                                        // (§9.1 subordinated — one step dim, never
                                        // accent, so it does not compete).
                                        PixelText {
                                            visible: thinkingActive
                                            text: (thinkTokens > 0 ? "· " + thinkTokens + " " : "")
                                                  + thinkToggle.dots
                                            color: Theme.textDim
                                        }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: { turn.userOpen = !think.expanded; turn.userSet = true; }
                                    }
                                }

                                Item {
                                    id: thinkReveal
                                    anchors { top: thinkToggle.bottom; left: parent.left; right: parent.right }
                                    clip: true
                                    height: think.expanded ? thinkBody.height : 0
                                    Behavior on height {
                                        NumberAnimation { duration: motion.ms(motion.slideMs)
                                                          easing.type: motion.slideEasing }
                                    }
                                    Rectangle {
                                        anchors { left: parent.left; leftMargin: 3
                                                  top: parent.top; bottom: parent.bottom }
                                        width: Theme.ctrlBorder
                                        color: Theme.border
                                    }
                                    PixelText {
                                        id: thinkBody
                                        anchors { top: parent.top; left: parent.left; right: parent.right
                                                  leftMargin: 12 }
                                        wrapMode: Text.Wrap
                                        text: thinking
                                        color: Theme.textDim
                                    }
                                }
                            }

                            // The turn's text. User prompts and error lines stay
                            // verbatim on PixelText (PlainText — never interpreted,
                            // the shared guard). A model row with no content yet
                            // shows "…" only when nothing else is speaking (no
                            // reasoning block carrying the wait).
                            PixelText {
                                width: parent.width
                                wrapMode: Text.Wrap
                                visible: text !== ""
                                text: isUser || isError ? body
                                      : (body === "" && streaming
                                         ? (thinking !== "" ? "" : "…") : "")
                                color: isError ? Theme.crit : Theme.text
                            }

                            // The model's answer, rendered as Markdown (the reply
                            // comes back in it — docs/DESIGN.md §2). Only the
                            // assistant body; user text and errors above stay plain.
                            MarkdownText {
                                width: parent.width
                                visible: !isUser && !isError && body !== ""
                                text: body
                            }
                        }
                    }
                }
            }

            // Follow the newest turn to the bottom while it streams; when idle,
            // leave the scroll where he put it so he can read back up the log.
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
                // The pair, not one half of it: the whole QFont carries
                // NoAntialias (the only lever that reaches the rasteriser on an
                // editable item — docs/DESIGN.md §2.2), and NativeRendering is
                // what stops Qt drawing it through the distance-field renderer.
                // Shipped with the font alone, which is why the box he types
                // into came out aliased and blurry while every label around it
                // was crisp. Same pairing as editor's CodeView and board's
                // InputBox.
                font: Theme.editorFont
                renderType: Text.NativeRendering
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
                    if (Ollama.busy) {
                        Ollama.cancel();
                        // cancel() fires no replyDone/replyError, so settle the
                        // in-flight row here (docs/DESIGN.md §10.6 — the row shows
                        // what happened, and a stopped stream is not still going).
                        if (win.activeIndex >= 0) {
                            chatLog.setProperty(win.activeIndex, "streaming", false);
                            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
                        }
                    } else win.send();
                }
            }
        }
    }
}
