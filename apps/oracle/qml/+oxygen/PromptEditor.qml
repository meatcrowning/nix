import QtQuick
import QtQuick.Controls as QQC

// The custom-prompt editor in an Oxygen session.
//
// `+plasma/PromptEditor.qml` gets the Frame, the TextArea and the button box
// from the style already; what it still carries is a floor painted `Theme.bg`.
// `Theme` is the wallpaper-derived palette the Hyprland desktop runs on, and in
// a Plasma session the window's colours come from KColorScheme instead — so
// that one Rectangle is the panel standing on a colour nothing else in the
// window is wearing. The floor here is the SYSTEM window colour, read off the
// item's own palette (the KDE platform theme fills it), so the panel stands on
// what every real widget in the same window stands on.
//
// No appear/disappear transition on purpose: this is a stacked-widget swap in
// Oxygen's terms, and `StackedWidgetTransitionsEnabled` is false by default
// (kstyle/oxygen.kcfg) — the style's answer is that the panel is simply there.
//
// Same API as ../PromptEditor.qml — `load(text)`, `saved(text)`, `cancelled()`.
Item {
    id: root
    property string face: "oxygen"
    signal saved(string text)
    signal cancelled()

    function load(t) {
        area.text = t;
        root.visible = true;
        area.forceActiveFocus();
    }

    visible: false
    implicitHeight: 220

    // The editor floats over the conversation, so it needs a floor of its own
    // or the view reads straight through it. A Frame's relief is an outline,
    // not a surface.
    Rectangle {
        anchors.fill: parent
        color: root.palette.window
    }

    QQC.Frame {
        id: frame
        anchors.fill: parent

        QQC.Label {
            id: heading
            anchors { top: parent.top; left: parent.left; right: parent.right }
            text: "Your custom system prompt"
            elide: Text.ElideRight
            // The style's own subordinated text, not a fraction of the live
            // colour: KColorScheme's disabled foreground is what Oxygen dims a
            // caption with, and it is legible against this window colour by
            // construction.
            enabled: false
        }

        QQC.ScrollView {
            anchors { top: heading.bottom; topMargin: 6
                      left: parent.left; right: parent.right
                      bottom: buttons.top; bottomMargin: 6 }
            clip: true

            QQC.TextArea {
                id: area
                wrapMode: QQC.TextArea.Wrap
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

        // The platform's own order, words and icons — which button sits where
        // is a desktop convention, not this app's choice.
        QQC.DialogButtonBox {
            id: buttons
            anchors { bottom: parent.bottom; right: parent.right }
            standardButtons: QQC.DialogButtonBox.Save | QQC.DialogButtonBox.Cancel
            padding: 0
            // Inside a Frame already; a button box's own surface would be a
            // second relief on the same rectangle.
            background: null
            onAccepted: { root.visible = false; root.saved(area.text); }
            onRejected: { root.visible = false; root.cancelled(); }
        }
    }
}
