import QtQuick
import QtWebEngine

// The page's alert() / confirm() / prompt() / beforeunload, drawn in surfer's
// own theme.
//
// This is NOT optional chrome. A QML WebEngineView with no
// onJavaScriptDialogRequested handler doesn't fall back to a default dialog —
// Chromium auto-REJECTS the request: prompt() returns null, confirm() returns
// false and alert() vanishes, all instantly and silently. Any page whose flow
// is gated on a prompt (the 4chan collage userscript, most "are you sure?"
// paths) then dead-ends with no visible reason.
//
// The request object is held across the event loop while the dialog is up —
// the documented pattern for custom dialogs, and what makes it modal: the
// page's JS stays blocked inside the prompt() call until dialogAccept/Reject.
// Because of that block a view can only ever have one dialog outstanding, but
// two TABS can, so requests queue rather than clobber each other.
Item {
    id: root
    visible: false
    z: 2800

    property var pending: null      // the JavaScriptDialogRequest being shown
    property var queue: []
    property int dtype: JavaScriptDialogRequest.DialogTypeAlert
    property string message: ""
    property string origin: ""

    readonly property bool isPrompt: dtype === JavaScriptDialogRequest.DialogTypePrompt
    readonly property bool isAlert:  dtype === JavaScriptDialogRequest.DialogTypeAlert

    function show(request) {
        request.accepted = true;    // "we'll handle it" — suppresses the auto-reject
        if (pending) { queue.push(request); return; }
        present(request);
    }

    function present(request) {
        pending  = request;
        dtype    = request.type;
        message  = request.message;
        origin   = ("" + request.securityOrigin).replace(/^[a-z]+:\/\//, "").replace(/\/$/, "");
        field.text = request.defaultText;
        root.visible = true;
        // steal the keyboard from the WebEngineView: the prompt's field must
        // take typing (a focus scope wouldn't hand it over on its own).
        if (isPrompt) { field.forceActiveFocus(); field.selectAll(); }
        else keySink.forceActiveFocus();
    }

    function finish() {
        pending = null;
        root.visible = false;
        if (queue.length > 0) present(queue.shift());
    }

    // Both answers go through try/finish: the tab that raised the dialog can be
    // closed from the titlebar while it's up (our scrim only covers the page),
    // which invalidates the held request — without the guard the throw would
    // skip finish() and leave an undismissable dialog over a dead view.
    function accept() {
        if (!pending) return;
        // dialogAccept's argument is only read for a prompt; alert/confirm ignore it
        try { pending.dialogAccept(isPrompt ? field.text : ""); } catch (e) {}
        finish();
    }
    function reject() {
        if (!pending) return;
        // an alert has no cancel — dismissing it IS accepting it, and rejecting
        // a beforeunload is what keeps the user on the page.
        try {
            if (isAlert) pending.dialogAccept("");
            else pending.dialogReject();
        } catch (e) {}
        finish();
    }

    // Full-window scrim: dims the page AND swallows clicks, so the page can't be
    // driven while it's blocked waiting on this answer. Clicking out cancels.
    MouseArea { anchors.fill: parent; onClicked: root.reject() }
    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.5) }

    Item {
        id: keySink
        Keys.onEscapePressed: root.reject()
        Keys.onReturnPressed: root.accept()
        Keys.onEnterPressed: root.accept()
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(420, root.width - 40)
        height: box.implicitHeight + 24
        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        MouseArea { anchors.fill: parent }   // swallow clicks inside the dialog

        Column {
            id: box
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 12 }
            spacing: 10

            // which page is asking — a page can put anything in `message`, so
            // the origin is the one trustworthy line in the box.
            PixelText {
                width: parent.width
                elide: Text.ElideRight
                text: root.origin !== "" ? root.origin + " says" : "this page says"
                color: Theme.accent
            }

            PixelText {
                width: parent.width
                wrapMode: Text.Wrap
                maximumLineCount: 12
                elide: Text.ElideRight
                text: root.message
                color: Theme.text
            }

            Rectangle {
                visible: root.isPrompt
                width: parent.width
                height: 24
                color: Theme.bgAlt
                border.color: Theme.accent
                border.width: 1
                TextInput {
                    id: field
                    anchors { fill: parent; margins: 4 }
                    verticalAlignment: TextInput.AlignVCenter
                    color: Theme.text
                    font.family: Theme.font
                    font.pixelSize: Theme.fontSize
                    renderType: Text.NativeRendering
                    clip: true
                    onAccepted: root.accept()
                    Keys.onEscapePressed: root.reject()
                }
            }

            Row {
                anchors.right: parent.right
                spacing: 6
                BrowserButton {
                    visible: !root.isAlert
                    label: root.dtype === JavaScriptDialogRequest.DialogTypeBeforeUnload ? "stay" : "cancel"
                    onClicked: root.reject()
                }
                BrowserButton {
                    label: root.dtype === JavaScriptDialogRequest.DialogTypeBeforeUnload ? "leave" : "ok"
                    onClicked: root.accept()
                }
            }
        }
    }
}
