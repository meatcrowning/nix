import QtQuick
import QtQuick.Controls

// The custom-prompt editor in a Plasma session: a real `Frame` holding a real
// `TextArea` in a `ScrollView`, with a `DialogButtonBox` — the KStyle's own
// relief, focus frame, scrollbar and button order, not an imitation of them
// (apps/AGENTS.md → kdeshell).
//
// It is the panel this face was missing entirely: Settings ▸ Edit Custom
// Prompt… in a KDE-chromed window put an accent-bordered aero box with
// lowercase pixel-font `cancel` / `save` on screen, inches from the real Oxygen
// buttons on the toolbar. The WORDS are the style's here too — a KDE dialog
// says Cancel and Save, capitalised, in the order and with the icons the
// platform picks.
//
// Same API as ../PromptEditor.qml — `load(text)`, `saved(text)`, `cancelled()`
// — so Root.qml is untouched; the file selector picks between the two.
Item {
    id: root
    property string face: "plasma"
    signal saved(string text)
    signal cancelled()

    function load(t) {
        area.text = t;
        root.visible = true;
        area.forceActiveFocus();
    }

    visible: false
    implicitHeight: 220

    // The editor floats over the conversation, so it needs a floor of its own:
    // a Frame is a frame, and the view would otherwise read straight through
    // the panel. The window's own colour is what a KDE dialog stands on.
    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }

    Frame {
        id: frame
        anchors.fill: parent

        Label {
            id: heading
            anchors { top: parent.top; left: parent.left; right: parent.right }
            text: "Your custom system prompt"
            elide: Text.ElideRight
            opacity: 0.75
        }

        ScrollView {
            anchors { top: heading.bottom; topMargin: 6
                      left: parent.left; right: parent.right
                      bottom: buttons.top; bottomMargin: 6 }
            clip: true

            TextArea {
                id: area
                wrapMode: TextArea.Wrap
                persistentSelection: true
                placeholderText: "Write the base instructions the model gets every turn…"
                Keys.onPressed: function (e) {
                    if (e.key === Qt.Key_Escape) {
                        root.visible = false;
                        root.cancelled();
                        e.accepted = true;
                    }
                }
            }
        }

        // The platform's own order and icons — which button sits where is a
        // desktop convention, not this app's choice.
        DialogButtonBox {
            id: buttons
            anchors { bottom: parent.bottom; right: parent.right }
            standardButtons: DialogButtonBox.Save | DialogButtonBox.Cancel
            padding: 0
            background: null
            onAccepted: { root.visible = false; root.saved(area.text); }
            onRejected: { root.visible = false; root.cancelled(); }
        }
    }
}
