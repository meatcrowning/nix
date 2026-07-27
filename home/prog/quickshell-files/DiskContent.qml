import QtQuick
import Quickshell

// One used/total bar per mounted drive, plus a SMART line for the drives that
// report it, and an inline rename that writes the real filesystem label.
//
// A pure view: everything it shows, and every script that produces it, lives in
// the Disks singleton. Being on screen is the only thing this contributes — hence
// `active`, which is what actually starts and stops the polling.
Item {
    id: root

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility. A `true` default would mean a
    // grid tile polls once at construction, before that Binding has applied —
    // measured as a full /proc scan and a drive scan on every reload, for a
    // widget nobody was looking at.
    property bool active: false
    property int pad: 10
    readonly property real inner: Math.max(160, width - 24)

    implicitWidth: 300
    implicitHeight: pad * 2 + col.implicitHeight

    onActiveChanged: Disks.watch(root, active)
    Component.onCompleted: Disks.watch(root, active)
    Component.onDestruction: Disks.watch(root, false)

    Column {
        id: col
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        spacing: 8

        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "disks"
            color: Theme.accent
        }

        Repeater {
            model: Disks.drives
            Column {
                required property var modelData
                readonly property real pct: modelData.size > 0 ? modelData.used / modelData.size : 0
                readonly property var sm: Disks.smartFor(modelData.src)
                width: root.inner
                spacing: 2

                Row {
                    width: parent.width
                    spacing: 4

                    // open the standalone filer rooted at this drive (left of the
                    // name). filer takes the directory as its first argument.
                    BrowserButton {
                        id: browseBtn
                        anchors.verticalCenter: parent.verticalCenter
                        label: "open"
                        // NixPath.run, not execDetached: `filer` is one of the
                        // vendored nix apps and the panel's PATH on book is
                        // Fedora's, so a bare exec silently did nothing there.
                        onClicked: NixPath.run(["filer", modelData.mount])
                    }

                    // name: click to rename (edits the real fs label), or an
                    // inline text field while renaming this drive
                    Item {
                        width: parent.width - sizeText.width - browseBtn.width - 8
                        height: 16

                        PixelText {
                            id: nameLabel
                            visible: Disks.renaming !== modelData.src
                            width: parent.width
                            elide: Text.ElideRight
                            // Glyphs.px HERE, not at the Disks ingest: the inline
                            // editor below prefills from `modelData.label` and
                            // hands it to `Disks.relabel()`, which writes the
                            // filesystem label for real.
                            text: Glyphs.px(modelData.label && modelData.label.length
                                  ? modelData.label : Disks.baseName(modelData.mount))
                                  + (modelData.rota ? "" : " *")  // star marks SSD
                            color: Theme.text
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.IBeamCursor
                                onClicked: {
                                    Disks.renaming = modelData.src;
                                    nameEdit.text = modelData.label || "";
                                    nameEdit.forceActiveFocus();
                                    nameEdit.selectAll();
                                }
                            }
                        }
                        Rectangle {
                            visible: Disks.renaming === modelData.src
                            anchors.fill: parent
                            color: Theme.bgAlt
                            border.color: Theme.accent
                            border.width: 1
                            TextInput {
                                id: nameEdit
                                anchors { fill: parent; leftMargin: 3; rightMargin: 3 }
                                verticalAlignment: TextInput.AlignVCenter
                                color: Theme.accent
                                font.family: Theme.font
                                font.pixelSize: Theme.fontSize
                                renderType: Text.NativeRendering
                                clip: true
                                onAccepted: {
                                    if (text && text !== modelData.label)
                                        Disks.relabel(modelData.src, modelData.fstype, text);
                                    else Disks.renaming = "";
                                }
                                Keys.onEscapePressed: Disks.renaming = ""
                            }
                        }
                    }

                    PixelText {
                        id: sizeText
                        anchors.verticalCenter: parent.verticalCenter
                        text: Disks.fmtG(modelData.used) + "/" + Disks.fmtG(modelData.size)
                        color: Theme.textDim
                    }
                }

                // used/total bar
                Rectangle {
                    width: parent.width
                    height: 8
                    color: Theme.bgAlt
                    border.width: 1
                    border.color: Theme.border
                    Rectangle {
                        anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 1 }
                        width: Math.round((parent.width - 2) * parent.parent.pct)
                        color: parent.parent.pct >= 0.9 ? Theme.crit
                             : parent.parent.pct >= 0.75 ? Theme.warn : Theme.accent
                    }
                }

                // SMART line for the drives that report it
                PixelText {
                    visible: parent.sm !== null
                    text: {
                        const s = parent.sm;
                        if (!s) return "";
                        let bits = [];
                        if (s.health) bits.push(s.health === "PASSED" ? "ok" : "FAIL");
                        if (s.temp) bits.push(s.temp + "C");
                        if (s.wear) bits.push("wear " + s.wear + "%");
                        if (s.poh) bits.push(Math.round(s.poh / 24) + "d on");
                        return "smart: " + bits.join("  ");
                    }
                    color: (parent.sm && parent.sm.health === "FAILED") ? Theme.crit : Theme.textDim
                }
            }
        }

        PixelText {
            visible: Disks.drives.length === 0
            anchors.horizontalCenter: parent.horizontalCenter
            text: "reading..."
            color: Theme.textDim
        }
    }
}
