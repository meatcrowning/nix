import QtQuick
import QtQuick.Window

// The sudo password dialog, drawn entirely by us.
//
// Every pixel here is ours: banner, field, buttons, focus ring. Nothing comes
// from a Qt style or a Plasma colour scheme, which is the point — ksshaskpass
// rendered light on book and dark-ish on top because it took whatever KDE
// theme the machine had. Colours are Theme.* (the live wal palette parsed from
// the panel's Theme.qml by main.py), text is the pixel font at Theme.fontSize,
// so this reads as the same desktop as the bar and the other apps on both
// hosts.
//
// ASCII only in every label. "More Perfect DOS VGA" has no ellipsis, minus sign
// or arrows, and one missing glyph drops the whole line onto a fallback font
// with a different ascent, which clips.
//
// The window is fixed-size and its app_id is `vista-askpass`; hyprland.lua
// centres, pins and dims around it, and the panel dims its own bar while it
// exists.
Window {
    id: win

    readonly property int pad: 16

    // Size is computed ONCE into properties of its own, and width/minimum/maximum
    // all read those. Writing `minimumHeight: height` instead makes the height
    // binding self-referential, and Qt resolves that loop by collapsing the
    // window to its minimum — measured at 520x32 before this was split out, i.e.
    // the dialog was a sliver with the whole body clipped away.
    readonly property int fixedWidth: 520
    readonly property int fixedHeight: banner.height + body.implicitHeight + pad * 2

    title: "sudo"
    width: fixedWidth
    height: fixedHeight
    minimumWidth: fixedWidth
    maximumWidth: fixedWidth
    minimumHeight: fixedHeight
    maximumHeight: fixedHeight
    visible: true
    color: Theme.bg

    // Closing the window (titlebar [x], compositor close) is a cancel: exit 1,
    // nothing on stdout. Fail closed.
    onClosing: Sudo.cancel()

    function submit() {
        // Empty is still a valid answer to hand sudo — it fails the auth, which
        // is the correct outcome, and refusing to submit would just wedge a
        // caller waiting on us.
        Sudo.accept(field.text);
    }

    // ---- banner: the "this is a privilege prompt" strip ----
    Rectangle {
        id: banner
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: Theme.lineHeight + 18
        color: Theme.highlight

        // accent rule down the left edge and along the bottom, the same 2px the
        // bar's accent strip and the window border use
        Rectangle {
            anchors { top: parent.top; bottom: parent.bottom; left: parent.left }
            width: 2
            color: Theme.accent
        }
        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 2
            color: Theme.border
        }

        PixelText {
            anchors { verticalCenter: parent.verticalCenter; left: parent.left; leftMargin: win.pad }
            text: "USER ACCOUNT CONTROL"
            color: Theme.accent
        }
    }

    // ---- body ----
    Column {
        id: body
        anchors {
            top: banner.bottom; left: parent.left; right: parent.right
            topMargin: win.pad; leftMargin: win.pad; rightMargin: win.pad
        }
        spacing: 12

        PixelText {
            width: parent.width
            text: "An action needs administrator rights."
            color: Theme.text
            wrapMode: Text.WordWrap
        }

        // sudo's own prompt line. Shown, never echoed anywhere.
        PixelText {
            width: parent.width
            text: startPrompt
            color: Theme.textDim
            wrapMode: Text.WordWrap
        }

        // ---- why root is being asked for, and for what ----
        //
        // Two rows, both walled off in this one inset box under captions that
        // say where the text came from. That framing is the point: neither line
        // may read as the dialog's own voice, so neither can be used to talk the
        // user into approving something. main.py sanitizes both and PixelText
        // renders PlainText, so the worst a hostile caller manages is clamped,
        // inert prose inside this rectangle.
        //
        //   startReason  - $SUDO_ASKPASS_REASON, the caller's own words. UNTRUSTED,
        //                  and usually absent, because callers forget to set it.
        //   startCommand - the argv of the sudo process that is waiting on us,
        //                  read from /proc. Also untrusted text, but it is the
        //                  thing actually being authorised rather than a claim
        //                  about it, and it cannot be forgotten. It is what makes
        //                  a reason-less prompt still worth reading.
        Rectangle {
            width: parent.width
            height: reasonCol.implicitHeight + 16
            color: Theme.highlight
            border.width: 2
            border.color: Theme.border

            Column {
                id: reasonCol
                anchors {
                    left: parent.left; right: parent.right
                    verticalCenter: parent.verticalCenter
                    leftMargin: 10; rightMargin: 10
                }
                spacing: 4

                PixelText {
                    width: parent.width
                    text: startReason ? "REASON GIVEN BY THE CALLER"
                                      : "NO REASON GIVEN BY THE CALLER"
                    color: Theme.textDim
                }

                PixelText {
                    width: parent.width
                    visible: startReason !== ""
                    text: startReason
                    color: Theme.text
                    wrapMode: Text.WordWrap
                    maximumLineCount: 4
                    elide: Text.ElideRight
                }

                PixelText {
                    width: parent.width
                    visible: startCommand !== ""
                    text: "COMMAND SUDO IS ABOUT TO RUN"
                    color: Theme.textDim
                }

                PixelText {
                    width: parent.width
                    visible: startCommand !== ""
                    text: startCommand
                    color: Theme.text
                    wrapMode: Text.WrapAnywhere
                    maximumLineCount: 3
                    elide: Text.ElideRight
                }
            }
        }

        // ---- password field ----
        Rectangle {
            width: parent.width
            height: Theme.lineHeight + 14
            color: Theme.bgAlt
            border.width: 2
            border.color: field.activeFocus ? Theme.accent : Theme.border

            TextInput {
                id: field
                // Named so the headless harness (tools/askpass-selftest.py) can
                // reach the field without a screen. Never read by the app.
                objectName: "pwField"
                anchors {
                    fill: parent
                    leftMargin: 8; rightMargin: 8
                    topMargin: 2; bottomMargin: 2
                }
                verticalAlignment: TextInput.AlignVCenter
                clip: true

                font: Theme.editorFont   // whole QFont: NoAntialias (docs/DESIGN.md 2.2)
                renderType: Text.NativeRendering
                color: Theme.text
                selectionColor: Theme.accent
                selectedTextColor: Theme.bg

                echoMode: TextInput.Password
                // The default mask character is a bullet the pixel font does not
                // have; "*" is on the ASCII strikes and stays crisp.
                passwordCharacter: "*"
                // No "briefly show the last character" reveal.
                passwordMaskDelay: 0

                focus: true
                activeFocusOnPress: true

                onAccepted: win.submit()
                Keys.onEscapePressed: Sudo.cancel()
            }
        }

        PixelText {
            width: parent.width
            text: "Enter to confirm, Esc to cancel."
            color: Theme.textDim
        }

        // ---- buttons ----
        // Wrapped in a plain Item: a Column refuses to position a child that
        // carries horizontal anchors ("Cannot specify left, right, ... anchors
        // for items inside Column"), so the right-alignment has to happen one
        // level down, inside something that is not a positioner.
        Item {
            width: parent.width
            height: buttons.height

            Row {
                id: buttons
                anchors.right: parent.right
                spacing: 8

                Repeater {
                    model: [
                        { id: "ok",     label: "OK" },
                        { id: "cancel", label: "Cancel" },
                    ]

                    Rectangle {
                        id: btn
                        required property var modelData
                        readonly property bool primary: modelData.id === "ok"

                        width: Math.max(96, btnLabel.implicitWidth + 24)
                        height: Theme.lineHeight + 14
                        color: mouse.containsMouse ? Theme.highlight : Theme.bgAlt
                        border.width: 2
                        border.color: primary ? Theme.accent : Theme.border

                        PixelText {
                            id: btnLabel
                            anchors.centerIn: parent
                            text: btn.modelData.label
                            color: btn.primary ? Theme.text : Theme.textDim
                        }

                        MouseArea {
                            id: mouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            // Keep the keyboard on the field: a click must not
                            // leave Enter/Esc going nowhere.
                            onClicked: {
                                field.forceActiveFocus();
                                if (btn.primary)
                                    win.submit();
                                else
                                    Sudo.cancel();
                            }
                        }
                    }
                }
            }
        }
    }

    Component.onCompleted: {
        win.requestActivate();
        field.forceActiveFocus();
    }
}
