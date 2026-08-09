import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "../../qmlcommon"

// slsk's window: a search mode and a downloads mode, one window, no chrome
// strip of its own (the bar is the hyprvtb titlebar; this window only draws
// content, docs/DESIGN.md 12, 7.4). Every pixel here follows the design
// language -- Theme palette + pixel font, Motion, KineticListView + VScroll.
Window {
    id: win

    // Focus-aware foreground, in lock-step with the titlebar (filer's idiom,
    // docs/DESIGN.md 3.1.1).
    // §3.1.1's app-side fade is RETIRED — his board call, 2026-08-09: with
    // "dim unfocused" on, the native decoration:dim_inactive scrim is the ONE
    // dimming mechanism, and an app that also greys its own foreground reads
    // darker than a plain window. The window always renders its focused tones;
    // the compositor dims the whole surface. Re-arm by restoring `win.active`
    // here — the plumbing is all still wired.
    readonly property bool renderActive: true
    readonly property color fgAccent: renderActive ? Theme.accent  : Theme.inactive
    readonly property color fgText:   renderActive ? Theme.text    : Theme.inactive
    readonly property color fgDim:    renderActive ? Theme.textDim : Theme.inactive

    Motion { id: motion }

    property string mode: startMode === "downloads" ? "downloads" : "search"
    property string lastQuery: Settings.get("query", "")
    property var results: []
    property var transfers: []
    property string searchStatus: ""
    property string toastText: ""
    property color toastColor: Theme.info

    title: "slsk"
    width: 1000
    height: 760
    minimumWidth: 380
    minimumHeight: 260
    visible: true
    color: Theme.bg

    // column widths in character cells, measured against the pixel font
    readonly property real rowH: Math.round(Theme.fontSize * 1.9)
    readonly property real barH: Math.round(Theme.fontSize * 2.2)
    readonly property real inset: Theme.fontSize
    function cell(ch) { return Math.round(ch * Math.max(1, Theme.fontSize * 0.42)); }

    function switchMode(m) {
        mode = m;
        Settings.set("mode", m);
        if (m === "downloads") Slsk.refreshTransfers();
    }

    function runSearch() {
        var q = queryField.text.trim();
        if (q.length === 0) { searchStatus = "type a query"; return; }
        if (!Slsk.isLoggedIn) { searchStatus = "not logged in to Soulseek"; return; }
        results = [];
        searchStatus = "searching '" + q + "'";
        Settings.set("query", q);
        Slsk.startSearch(q);
    }

    function queueRow(r) {
        if (r && r.userraw && r.path) Slsk.queueDownload(r.userraw, r.path, r.sizeBytes);
    }

    function showToast(msg, kind) {
        toastText = msg;
        toastColor = (kind === "ok") ? Theme.ok
                    : (kind === "warn") ? Theme.warn
                    : (kind === "crit") ? Theme.crit : Theme.info;
        toastTimer.restart();
    }

    Component.onCompleted: {
        Slsk.refreshStatus();
        Titlebar.setFooter("slsk");
        if (mode === "downloads") Slsk.refreshTransfers();
    }
    Connections { target: Slsk; function onStatusChanged() {
        Titlebar.setFooter(Slsk.statusText);
    } }
    Connections { target: Slsk; function onToast(msg, kind) { win.showToast(msg, kind); } }
    Connections { target: Slsk; function onSearchUpdated(id, q, res) {
        win.results = res;
        searchStatus = res.length === 0 ? "no results for '" + q + "'"
                                        : res.length + (res.length === 1 ? " result" : " results") + " for '" + q + "'";
    } }
    Connections { target: Slsk; function onSearchError(id, err) {
        searchStatus = "search failed: " + err;
    } }
    Connections { target: Slsk; function onTransfersUpdated(t) { win.transfers = t; } }

    Timer { id: toastTimer; interval: 3200; onTriggered: toastText = "" }

    // ---- top bar: the two modes + the connection status ----
    RowLayout {
        id: topBar
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: barH
        anchors.leftMargin: 6
        spacing: 6

        ModeTab { label: "search";    active: win.mode === "search";    onClicked: win.switchMode("search") }
        ModeTab { label: "downloads"; active: win.mode === "downloads"; onClicked: win.switchMode("downloads") }

        Text {
            text: Slsk.statusText
            color: Slsk.isLoggedIn ? Theme.textDim : Theme.crit
            font { family: Theme.font; pixelSize: Theme.fontSize }
            elide: Text.ElideRight
            Layout.fillWidth: true
            verticalAlignment: Text.AlignVCenter
        }
    }

    Rectangle {
        id: divider
        anchors { left: parent.left; right: parent.right; top: topBar.bottom }
        height: 1
        color: Theme.border
    }

    // ---- search mode ----
    Column {
        id: searchMode
        visible: win.mode === "search"
        anchors { left: parent.left; right: parent.right; top: divider.bottom;
                  bottom: parent.bottom }
        anchors.leftMargin: win.inset
        anchors.rightMargin: win.inset
        anchors.topMargin: 6
        spacing: 6

        RowLayout {
            id: inputRow
            Layout.fillWidth: true
            spacing: 6
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: win.rowH - 4
                color: Theme.bgAlt
                radius: Theme.rounding
                border { color: Theme.border; width: Theme.ctrlBorder }
                TextInput {
                    id: queryField
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    anchors.leftMargin: 8
                    text: win.lastQuery
                    color: Theme.text
                    font { family: Theme.font; pixelSize: Theme.fontSize }
                    clip: true
                    selectByMouse: true
                    onAccepted: win.runSearch()
                }
            }
            Button {
                Layout.preferredWidth: Math.round(Theme.fontSize * 6)
                Layout.preferredHeight: win.rowH - 4
                label: Slsk.searching ? "..." : "search"
                fill: Theme.accent
                textColor: Theme.bg
                onClicked: win.runSearch()
            }
        }

        Text {
            text: searchStatus
            font { family: Theme.font; pixelSize: Theme.fontSize }
            color: Theme.textDim
            visible: searchStatus !== ""
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(Theme.fontSize * 1.6)
            spacing: 6
            HeaderCell { Layout.preferredWidth: win.cell(5);  text: "slot" }
            HeaderCell { Layout.fillWidth: true;               text: "file" }
            HeaderCell { Layout.preferredWidth: win.cell(20);  text: "user" }
            HeaderCell { Layout.preferredWidth: win.cell(11);  text: "size" }
        }

        KineticListView {
            id: resultsView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: win.results
            spacing: 1
            ScrollBar.vertical: VScroll { id: resScroll }
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredHeight: win.rowH
                spacing: 6
                Rectangle {
                    visible: rowArea.containsMouse
                    anchors.fill: parent
                    z: -1
                    color: Theme.highlight
                }
                Txt { Layout.preferredWidth: win.cell(5);   text: modelData.free ? "free" : "w"
                      colr: modelData.free ? Theme.ok : Theme.textDim }
                Txt { Layout.fillWidth: true;                 text: modelData.filename
                      colr: Theme.text; ell: true }
                Txt { Layout.preferredWidth: win.cell(20);    text: modelData.username; colr: Theme.textDim }
                Txt { Layout.preferredWidth: win.cell(11);    text: modelData.size;     colr: Theme.info }
                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    onDoubleClicked: win.queueRow(modelData)
                    onPressAndHold: win.queueRow(modelData)
                }
            }
        }
    }

    // ---- downloads mode ----
    Column {
        id: dlMode
        visible: win.mode === "downloads"
        anchors { left: parent.left; right: parent.right; top: divider.bottom;
                  bottom: parent.bottom }
        anchors.leftMargin: win.inset
        anchors.rightMargin: win.inset
        anchors.topMargin: 6

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(Theme.fontSize * 1.6)
            spacing: 6
            HeaderCell { Layout.preferredWidth: win.cell(16); text: "state" }
            HeaderCell { Layout.fillWidth: true;              text: "file" }
            HeaderCell { Layout.preferredWidth: win.cell(18); text: "progress" }
        }

        KineticListView {
            id: dlView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: win.transfers
            spacing: 4
            ScrollBar.vertical: VScroll { id: dlScroll }
            delegate: Item {
                required property var modelData
                width: dlView.width
                height: Math.round(Theme.fontSize * 3.1)

                Rectangle {
                    visible: dlRow.containsMouse
                    anchors.fill: parent
                    color: Theme.highlight
                }

                RowLayout {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 6
                    Column {
                        Layout.fillWidth: true
                        Layout.preferredHeight: parent.parent.height
                        spacing: 2
                        Txt { width: parent.width; text: modelData.state;  colr: stateColor(modelData); fscale: 0.95 }
                        Txt { width: parent.width; text: modelData.filename; colr: Theme.text; ell: true; fscale: 1.05 }
                        Txt { width: parent.width; text: meta(modelData); colr: Theme.textDim; fscale: 0.95 }
                    }
                    Rectangle {
                        Layout.preferredWidth: win.cell(18) - 2
                        Layout.preferredHeight: Math.round(Theme.fontSize * 2.2)
                        color: Theme.bgAlt
                        // radius deliberately unbound: the progress fill below
                        // sits flush in this trough and stays square.
                        border { color: Theme.border; width: Theme.ctrlBorder }
                        Rectangle {
                            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                            width: parent.width * (modelData.percent / 100)
                            color: modelData.completed ? Theme.ok
                                 : (modelData.percent > 0 ? Theme.accent : Theme.dim)
                        }
                    }
                    Text {
                        visible: modelData.canCancel
                        text: "x"
                        font { family: Theme.font; pixelSize: Theme.fontSize }
                        color: Theme.crit
                        Layout.preferredWidth: win.cell(2)
                        verticalAlignment: Text.AlignVCenter
                        MouseArea {
                            anchors.fill: parent
                            onClicked: Slsk.cancelDownload(modelData.userraw, modelData.id)
                        }
                    }
                }

                MouseArea {
                    id: dlRow
                    anchors.fill: parent
                    hoverEnabled: true
                    onDoubleClicked: { if (modelData.canCancel) Slsk.cancelDownload(modelData.userraw, modelData.id) }
                }
            }
        }
    }

    // ---- toast ----
    Rectangle {
        visible: toastText !== ""
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 12 }
        height: Math.round(Theme.fontSize * 2.2)
        width: Math.min(win.width - 40, Math.max(120, toastText.length * Theme.fontSize * 0.62))
        color: Theme.bgAlt
        radius: Theme.rounding
        border { color: toastColor; width: Theme.ctrlBorder }
        Text {
            anchors.centerIn: parent
            text: toastText
            color: toastColor
            font { family: Theme.font; pixelSize: Theme.fontSize }
        }
    }

    onClosing: {
        Settings.set("mode", mode);
        Qt.quit();
    }

    function stateColor(t) {
        var s = t.state || "";
        if (s.indexOf("Completed") === 0) return Theme.ok;
        if (s.indexOf("Queued") === 0 || s.indexOf("Initializing") === 0) return Theme.warn;
        return Theme.text;
    }
    function meta(t) {
        var parts = [];
        if (t.dir) parts.push(t.dir);
        parts.push(t.size + (t.completed ? "" : " of " + t.done));
        if (!t.completed && t.speed) parts.push(t.speed);
        return parts.join("  " + String.fromCharCode(183) + "  ");
    }

    component ModeTab: Rectangle {
        property string label
        property bool active
        signal clicked()
        Layout.preferredWidth: Math.round(Theme.fontSize * (label.length + 2))
        Layout.preferredHeight: Math.round(Theme.fontSize * 2)
        color: active ? Theme.accent : Theme.bgAlt
        radius: Theme.rounding
        border { color: Theme.border; width: Theme.ctrlBorder }
        Text {
            anchors.centerIn: parent
            text: label
            color: active ? Theme.bg : Theme.text
            font { family: Theme.font; pixelSize: Theme.fontSize }
        }
        MouseArea { anchors.fill: parent; onClicked: clicked() }
    }

    component Button: Rectangle {
        property string label
        property color fill
        property color textColor
        signal clicked()
        color: fill
        radius: Theme.rounding
        border { color: Theme.border; width: Theme.ctrlBorder }
        Text {
            anchors.centerIn: parent
            text: label
            color: textColor
            font { family: Theme.font; pixelSize: Theme.fontSize }
        }
        MouseArea { anchors.fill: parent; onClicked: clicked() }
    }

    component HeaderCell: Text {
        color: Theme.textDim
        font { family: Theme.font; pixelSize: Theme.fontSize }
        verticalAlignment: Text.AlignVCenter
    }

    component Txt: Text {
        property string colr: Theme.text
        property bool ell: false
        property real fscale: 1
        color: colr
        elide: ell ? Text.ElideRight : Text.ElideNone
        verticalAlignment: Text.AlignVCenter
        font { family: Theme.font; pixelSize: Math.round(Theme.fontSize * fscale) }
        clip: true
    }
}
