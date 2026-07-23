import QtQuick
import QtQuick.Window

// viewer's window: a full-window image reader with its controls in the hyprvtb
// titlebar. The flip-through set + start index come from main.py (startImages /
// startIndex — the opened file's sibling images, name-sorted); this holds the
// current index and drives the ImageViewer. Being a real Wayland Window, the
// hyprvtb plugin gives it the same vertical titlebar / drag / resize / minimize
// as filer and surfer; `Titlebar` (context property) bridges its button column.
Window {
    id: win

    property var images: startImages    // [{ name, path }]
    property int index: startIndex
    readonly property bool has: images.length > 0 && index >= 0 && index < images.length
    readonly property string curPath: has ? images[index].path : ""
    readonly property string curName: has ? images[index].name : ""

    // Focus-aware foreground, in lock-step with the titlebar (see filer).
    readonly property bool act: win.active

    title: has ? curName : "viewer"
    width: 900
    height: 620
    minimumWidth: 320
    minimumHeight: 240
    visible: true
    color: Theme.bg

    onClosing: Qt.quit()

    function next() { if (images.length) index = (index + 1) % images.length; }
    function prev() { if (images.length) index = (index - 1 + images.length) % images.length; }

    // ---- hyprvtb titlebar buttons: the viewer controls ----
    // state: 0 normal, 2 disabled (flip greys out on a single image).
    readonly property var tbButtons: {
        const multi = images.length > 1 ? 0 : 2;
        return [
            { id: "prev",    label: "‹",   state: multi, tip: "previous image" },
            { id: "next",    label: "›",   state: multi, tip: "next image" },
            { id: "zoomout", label: "−",   state: 0,     tip: "zoom out" },
            { id: "zoomin",  label: "+",   state: 0,     tip: "zoom in" },
            { id: "fit",     label: "fit", state: 0,     tip: "fit to window" },
            { id: "close",   label: "×",   state: 0,     tip: "close" },
        ];
    }
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    // footer readout at the bottom of the inner column: position + name.
    readonly property string footerStr: has ? ((index + 1) + "/" + images.length + "  " + curName) : ""
    onFooterStrChanged: Titlebar.setFooter(footerStr)

    Component.onCompleted: { Titlebar.setButtons(tbButtons); Titlebar.setFooter(footerStr); }

    Connections {
        target: Titlebar
        function onClicked(id) {
            switch (id) {
            case "prev":    win.prev();               break;
            case "next":    win.next();               break;
            case "zoomout": viewer.zoomBy(0.8);       break;
            case "zoomin":  viewer.zoomBy(1.25);      break;
            case "fit":     viewer.fit();             break;
            case "close":   Qt.quit();                break;
            }
        }
    }

    ImageViewer {
        id: viewer
        anchors.fill: parent
        focus: true
        winActive: win.active
        source: win.curPath !== "" ? ("file://" + encodeURI(win.curPath)) : ""
        name: win.curName
        onNext: win.next()
        onPrev: win.prev()
        onCloseRequested: Qt.quit()
    }
}
