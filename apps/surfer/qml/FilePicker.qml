import QtQuick
import QtWebEngine

// The file dialog a page's <input type=file> (or upload button) pops — which is
// FILER, run as `filer --pick`, exactly the way KDE hands its file dialogs to
// Dolphin. This file is the QUEUE and the plumbing; there is no UI in it.
//
// Why not a picker of our own, which is what this was until 2026-08-07: it was
// a second, worse file browser — no tree, no thumbnails, no preview grid, no
// sort, no `:top` remote browsing, no editable path — and every fix had to be
// made twice. filer already IS a file dialog (`apps/filer/pick.py`, the
// FileChooser portal backend's UI), so surfer speaks that same spec/result
// protocol: `Files.pick(token, spec)` writes the spec, runs filer, and answers
// on `Files.picked(token, paths)`; an empty list means cancelled. QtWebEngine
// is still imported here for the FileDialogRequest mode enum, nothing else.
//
// With no onFileDialogRequested handler the QML WebEngineView auto-rejects, so
// the picker never opens at all — the click registers, onchange never fires,
// and the page looks broken. Hence the handler still lives here.
//
// Queued PER VIEW, and only the current tab's front request is acted on, so a
// background tab cannot throw a dialog in front of the page you are on. Unlike
// a JS dialog a file request does NOT block the page's JS, so a page can have
// several outstanding; they queue in request order.
QtObject {
    id: root

    // the view whose picker may be shown — bound to win.current by Main.qml
    property var currentView: null

    property var pending: null         // the FileDialogRequest being answered
    property var pendingView: null     // and the view it came from
    property string pendingToken: ""   // ...and the token filer's answer carries
    property var buckets: []           // [{ view, items: [request, …] }]
    property int rev: 0                // bumped on every queue change (tab tooltips)
    property int seq: 0

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
        request.accepted = true;       // "we'll handle it" — suppresses the auto-reject
        bucketFor(view, true).items.push(request);
        rev += 1;
        sync();
    }

    // tab closing — see JsDialog.dropView for why this can't be a liveness check
    function dropView(view) {
        var live = [];
        for (var i = 0; i < buckets.length; i++)
            if (buckets[i].view !== view) live.push(buckets[i]);
        buckets = live;
        if (pendingView === view) {
            // The dialog outlives its tab as a window, so it has to be taken
            // down with it; killing it leaves no result file, which filer's
            // protocol already reads as a cancel.
            Files.cancelPick(pendingToken);
            pending = null; pendingView = null; pendingToken = "";
        }
        rev += 1;
        sync();
    }

    // Only ONE dialog at a time, and only for the tab you are looking at. A
    // request from a background tab waits at its bucket's head until that tab
    // is current — a file dialog is a window here, and one thrown up over
    // another page would be a page you did not ask stealing the keyboard.
    function sync() {
        if (pending) return;
        var b = bucketFor(currentView, false);
        if (b && b.items.length > 0) present(b.items[0], currentView);
    }

    function present(request, view) {
        pending      = request;
        pendingView  = view;
        seq         += 1;
        pendingToken = "pick" + seq;
        Files.pick(pendingToken, specFor(request));
    }

    // The spec filer's picker mode reads (apps/filer/pick.py). Chromium's four
    // modes map onto its three: open / open-multiple / a folder / save-as.
    function specFor(request) {
        var mode = "open", multiple = false;
        if (request.mode === FileDialogRequest.FileModeOpenMultiple) multiple = true;
        else if (request.mode === FileDialogRequest.FileModeUploadFolder) mode = "dir";
        else if (request.mode === FileDialogRequest.FileModeSave) mode = "save";
        return {
            "mode": mode,
            "multiple": multiple,
            "title": mode === "save" ? "save as"
                   : mode === "dir"  ? "select a folder"
                   : multiple        ? "select files" : "select a file",
            "accept_label": mode === "save" ? "save" : "open",
            "current_folder": Files.startDir(),
            "current_name": request.defaultFileName || "",
            "filters": [],
        };
    }

    // filer answered. try/catch for the same reason as JsDialog: the tab can be
    // closed from the titlebar while the dialog is up, invalidating the held
    // request — the queue must still move on.
    property var conn: Connections {
        target: Files
        function onPicked(token, paths) {
            if (token !== root.pendingToken) return;   // a stale one; ignore
            var b = root.bucketFor(root.pendingView, false);
            if (b) b.items.shift();
            var req = root.pending;
            root.pending = null;
            root.pendingView = null;
            root.pendingToken = "";
            try {
                if (paths.length > 0) {
                    Files.rememberDir(Files.parentOf(paths[0]));
                    req.dialogAccept(paths);
                } else {
                    req.dialogReject();
                }
            } catch (e) {}
            root.rev += 1;
            root.sync();
        }
    }
}
