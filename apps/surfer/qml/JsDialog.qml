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
//
// Queues are PER VIEW, and only the current tab's front request is ever shown:
// a dialog belongs to the page that raised it, so a background tab must not
// throw a modal over whatever you're reading. Switching tabs swaps the panel to
// that tab's dialog (or hides it); switching back brings the deferred one up
// untouched. Chromium proper auto-dismisses background-tab dialogs instead —
// deferring is friendlier here, since the page stays blocked either way and the
// tab's titlebar tooltip advertises that it's waiting (see win.waitingFor).
Item {
    id: root

    // The window's focus state, handed down (docs/DESIGN.md §3.1.1). A leaf
    // never reads Window.active itself: `Qt.application.state` is per-APPLICATION
    // and stays Active while another of surfer's windows takes focus.
    property bool winActive: true
    visible: false
    z: 2800

    // the view whose dialogs may be shown — bound to win.current by Main.qml
    property var currentView: null

    property var pending: null      // the JavaScriptDialogRequest on screen
    property var pendingView: null  // and the view it came from
    // [{ view, items: [request, …] }] — the shown request stays at its bucket's
    // head until it's answered, so hiding it on a tab switch is just forgetting
    // that it's on screen.
    property var buckets: []
    property int rev: 0             // bumped on every queue change (tab tooltips)

    property int dtype: JavaScriptDialogRequest.DialogTypeAlert
    property string message: ""
    property string origin: ""

    readonly property bool isPrompt: dtype === JavaScriptDialogRequest.DialogTypePrompt
    readonly property bool isAlert:  dtype === JavaScriptDialogRequest.DialogTypeAlert

    onCurrentViewChanged: sync()

    function bucketFor(view, make) {
        for (var i = 0; i < buckets.length; i++)
            if (buckets[i].view === view) return buckets[i];
        if (!make) return null;
        var b = { view: view, items: [] };
        buckets.push(b);
        return b;
    }
    function countFor(view) {
        var b = bucketFor(view, false);
        return b ? b.items.length : 0;
    }

    function show(view, request) {
        request.accepted = true;    // "we'll handle it" — suppresses the auto-reject
        bucketFor(view, true).items.push(request);
        rev += 1;
        sync();
    }

    // A tab is closing: its held requests die with the view, so drop them
    // unanswered (reaching into a request whose page is being torn down is not
    // safe). Driven from the view's Component.onDestruction — the only reliable
    // signal, since a JS reference to an already-destroyed QObject stays truthy
    // here, so liveness can't be tested after the fact.
    function dropView(view) {
        var live = [];
        for (var i = 0; i < buckets.length; i++)
            if (buckets[i].view !== view) live.push(buckets[i]);
        buckets = live;
        if (pendingView === view) { pending = null; pendingView = null; root.visible = false; }
        rev += 1;
        sync();
    }

    // Make the panel agree with the current tab: hide a dialog that isn't the
    // current view's, then show that view's front one if there is one.
    function sync() {
        if (pending && pendingView !== currentView) {
            pending = null;              // stays at its bucket's head, deferred
            pendingView = null;
            root.visible = false;
        }
        if (pending) return;
        var b = bucketFor(currentView, false);
        if (b && b.items.length > 0) present(b.items[0], currentView);
    }

    function present(request, view) {
        pending     = request;
        pendingView = view;
        dtype       = request.type;
        message     = request.message;
        origin      = ("" + request.securityOrigin).replace(/^[a-z]+:\/\//, "").replace(/\/$/, "");
        field.text  = request.defaultText;
        root.visible = true;
        // steal the keyboard from the WebEngineView: the prompt's field must
        // take typing (a focus scope wouldn't hand it over on its own).
        if (isPrompt) { field.forceActiveFocus(); field.selectAll(); }
        else keySink.forceActiveFocus();
    }

    // answered: drop it from its bucket and move on to whatever's behind it
    function finish() {
        var b = bucketFor(pendingView, false);
        if (b) b.items.shift();
        pending = null;
        pendingView = null;
        root.visible = false;
        rev += 1;
        sync();
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
        radius: Theme.rounding
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
                radius: Theme.rounding
                border.color: Theme.accent
                border.width: Theme.ctrlBorder
                TextInput {
                    id: field
                    anchors { fill: parent; margins: 4 }
                    verticalAlignment: TextInput.AlignVCenter
                    color: Theme.text
                    font: Theme.editorFontAt(Screen.devicePixelRatio)   // whole QFont: NoAntialias (docs/DESIGN.md 2.2)
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
                    winActive: root.winActive
                    visible: !root.isAlert
                    label: root.dtype === JavaScriptDialogRequest.DialogTypeBeforeUnload ? "stay" : "cancel"
                    onClicked: root.reject()
                }
                BrowserButton {
                    winActive: root.winActive
                    label: root.dtype === JavaScriptDialogRequest.DialogTypeBeforeUnload ? "leave" : "ok"
                    onClicked: root.accept()
                }
            }
        }
    }
}
