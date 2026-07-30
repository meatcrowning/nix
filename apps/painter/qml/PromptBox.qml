import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

Rectangle {
    id: box
    property string placeholder: ""
    property alias text: input.text
    property bool negative: false
    signal edited(string text)

    //: A prompt is prose, so it is spellchecked (`qmlcommon/SpellMarks.qml`) and
    //: right-clicking a marked word offers corrections. The MENU cannot live in
    //: here — this box is 64-130px tall and `CtxMenu` clamps itself into its own
    //: root — so the items travel up to Main.qml, which owns the one menu, in
    //: SCENE coordinates.
    signal menuRequested(real sx, real sy, var items)

    color: Theme.bg
    border.color: input.activeFocus ? Theme.accent : Theme.border
    border.width: 1

    KineticFlickable {
        id: flick
        anchors.fill: parent
        anchors.margins: 5
        contentWidth: width
        contentHeight: input.implicitHeight
        clip: true
        ScrollBar.vertical: VScroll {}

        TextEdit {
            id: input
            width: flick.width
            wrapMode: TextEdit.Wrap
            color: box.negative ? Theme.textDim : Theme.text
            font.family: Theme.font
            font.pixelSize: Theme.fontSize
            font.hintingPreference: Font.PreferFullHinting
            renderType: Text.NativeRendering
            // NO lineHeight/lineHeightMode HERE. They are Text-only properties;
            // QQuickTextEdit does not have them, so assigning them is a
            // component-creation error, not a no-op — it made PromptBox
            // unavailable, which took PromptEditor with it and left Main.qml
            // unable to load at all. painter could not start from 21534ca (the
            // kitty-exact pass, which added them by analogy with PixelText)
            // until this was removed. Qt offers no equivalent pin on an
            // editable text item, so this one surface leads at Qt's rounded
            // 16px rather than kitty's 15px cell; that is an accepted loss and
            // NOT an invitation to re-add these two lines.
            selectByMouse: true
            selectionColor: Theme.accent
            selectedTextColor: Theme.bg
            onTextChanged: box.edited(text)
            // Ctrl+Enter belongs to the window, not the editor.
            Keys.onPressed: function (e) {
                if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                        && (e.modifiers & Qt.ControlModifier)) {
                    e.accepted = false
                }
            }

            // §7.1: everything selectable is right-clickable. Left-drag
            // selection stays Qt's (`selectByMouse`); this takes the right
            // button only, so nothing else changes.
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.RightButton
                onPressed: function (m) {
                    var pos = input.positionAt(m.x, m.y)
                    var hasSel = input.selectionEnd > input.selectionStart
                    var items = marks.menuItems(pos).concat([
                        { label: "undo", enabled: input.canUndo,
                          trigger: () => input.undo() },
                        { label: "redo", enabled: input.canRedo,
                          trigger: () => input.redo() },
                        { separator: true },
                        { label: "cut", enabled: hasSel, trigger: () => input.cut() },
                        { label: "copy", enabled: hasSel, trigger: () => input.copy() },
                        { label: "paste", trigger: () => input.paste() },
                        { label: "select all", trigger: () => input.selectAll() }
                    ])
                    var p = mapToItem(null, m.x, m.y)
                    box.menuRequested(p.x, p.y, items)
                }
            }
        }

        SpellMarks {
            id: marks
            target: input
            viewport: flick
            x: input.x
            y: input.y
            width: input.width
            height: input.height
        }

        PixelText {
            visible: input.text === ""
            text: box.placeholder
            color: Theme.dim
        }
    }

}
