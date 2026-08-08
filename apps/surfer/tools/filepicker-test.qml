import QtQuick
import QtQuick.Window
import QtWebEngine
import "../qml"

// Offscreen fixture for tools/filepicker-test.py — the REAL FilePicker.qml with
// stand-ins for the two things it talks to: a page's FileDialogRequest (which
// only a live Chromium can mint, and which would need a WebEngineView and its
// profile) and the "view" it belongs to, here just a string.
//
// The stub carries the four fields FilePicker reads — `mode`, `defaultFileName`,
// `accepted`, and the two answer methods — so what is under test is the real
// queue, the real spec, and the real answer path.
Window {
    id: win
    width: 400
    height: 300
    visible: true

    FilePicker {
        id: picker
        objectName: "picker"
        currentView: "v1"
    }

    QtObject {
        id: fake
        objectName: "requests"

        // what the last answered request was told
        property var acceptedWith: null
        property bool rejected: false
        function reset() { acceptedWith = null; rejected = false; }

        property Component reqComp: Component {
            QtObject {
                property int mode: 0
                property string defaultFileName: ""
                property bool accepted: false
                function dialogAccept(paths) { fake.acceptedWith = paths; }
                function dialogReject() { fake.rejected = true; }
            }
        }

        function makeRequest(mode, name, view) {
            var r = reqComp.createObject(fake, { mode: mode, defaultFileName: name });
            picker.show(view, r);
            return r;
        }
    }
}
