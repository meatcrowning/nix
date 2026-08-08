import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

Rectangle {
    id: box
    property string placeholder: ""
    property bool negative: false
    signal edited(string text)

    // `value` is the MODEL's text; `input.text` is the editor's. They are synced
    // one way, on change, and never bound to each other — `text: root.gen.positive`
    // plus `onTextChanged -> root.set(...)` is a cycle, and the moment `gen`
    // started notifying properly (see Main.qml) it became a live binding loop on
    // every keystroke. The guard is the equality test: an echo of what was just
    // typed writes nothing, so the caret never jumps.
    property string value: ""
    // ...and the write itself is flagged, so pushing the model INTO the editor
    // does not come straight back out as a user edit. Without this the round
    // trip (value -> text -> edited -> gen -> value) re-enters inside one
    // evaluation pass and QML reports a binding loop, even though the values
    // agree by the end of it.
    property bool syncing: false
    onValueChanged: {
        if (input.text === value) return
        syncing = true
        input.text = value
        syncing = false
    }
    // The editor's own text, for callers that want to read it back.
    readonly property alias text: input.text

    //: A prompt is prose, so it is spellchecked (`qmlcommon/SpellMarks.qml`) and
    //: right-clicking a marked word offers corrections. The MENU cannot live in
    //: here — this box is 64-130px tall and `CtxMenu` clamps itself into its own
    //: root — so the items travel up to Main.qml, which owns the one menu, in
    //: SCENE coordinates.
    signal menuRequested(real sx, real sy, var items)

    // HOW TALL IS HIS DECISION. A prompt here runs from four words to the
    // multi-paragraph shot description a video model wants, and a fixed box
    // meant scrolling a 64px window through the second kind. The bottom edge is
    // a grab strip: drag it, and the height is remembered (`resized` -> Prefs,
    // in PromptEditor).
    // The drag writes `boxHeight`, a plain property, and `height` is bound to
    // it — writing `height` itself would destroy that binding, and the hidden
    // case below (video, no negative prompt) would never fold back to zero.
    property int boxHeight: 130
    property int minHeight: 40
    property int maxHeight: 600
    signal resized(int h)

    height: visible ? boxHeight : 0

    color: Theme.bg
    border.color: input.activeFocus ? Theme.accent : Theme.border
    border.width: 1

    KineticFlickable {
        id: flick
        anchors.fill: parent
        anchors.margins: 5
        anchors.bottomMargin: 7          // clear of the grab strip
        contentWidth: width
        contentHeight: input.height
        clip: true
        ScrollBar.vertical: VScroll {}

        TextEdit {
            id: input
            width: flick.width
            // THE WHOLE BOX IS THE TEXT BOX. A TextEdit is only as tall as its
            // content, so in a 130px prompt box holding one line, every click
            // below that first line hit nothing: the box looked like a text
            // area and behaved like a 16px strip. Filling the viewport hands
            // the empty space to the editor itself, so a click anywhere puts
            // the caret at the nearest position (the end, past the last line)
            // and a drag from empty space selects — Qt's own behaviour, not a
            // MouseArea imitating it. Content taller than the box still scrolls:
            // implicitHeight wins once it exceeds the viewport.
            height: Math.max(implicitHeight, flick.height)
            wrapMode: TextEdit.Wrap
            color: box.negative ? Theme.textDim : Theme.text
            font: Theme.editorFont   // whole QFont: NoAntialias (docs/DESIGN.md 2.2)
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
            // The selection SURVIVES the menu that acts on it. A TextEdit drops
            // its selection the moment it loses active focus, and opening
            // `CtxMenu` does exactly that — so `cut` and `copy` were offered
            // (the rows are enabled from the selection as it stood at the
            // right-click) and then ran against nothing. Same setting, same
            // reason, as editor's `CodeView`.
            persistentSelection: true
            selectionColor: Theme.accent
            selectedTextColor: Theme.bg
            onTextChanged: if (!box.syncing) box.edited(text)
            // Ctrl+Enter belongs to the window, not the editor.
            Keys.onPressed: function (e) {
                if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                        && (e.modifiers & Qt.ControlModifier)) {
                    e.accepted = false
                }
            }
            // Escape LETS GO of the box — the one thing it is for here. Handled
            // on the editor as well as at the window, because a focused text
            // item is exactly where a window-level Shortcut is least reliable.
            Keys.onEscapePressed: function (e) {
                root.releaseFocus()
                e.accepted = true
            }

            // §7.1: everything selectable is right-clickable. Left-drag
            // selection stays Qt's (`selectByMouse`); this takes the right
            // button only, so nothing else changes.
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.RightButton
                onPressed: function (m) {
                    // A right-click puts the keyboard in this box, exactly as a
                    // left-click does. The menu takes the focus while it is open
                    // and gives it back to whatever held it (`CtxMenu`), so
                    // without this a menu opened on an UNFOCUSED box handed the
                    // keyboard back to wherever it had been — and `select all`
                    // there is a selection nothing can then delete.
                    input.forceActiveFocus()
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

    // The grab strip. 5px drawn, ±3px of grab margin across it — the same
    // shape as the window's own splitter, so a drag target behaves the same
    // way everywhere in this app.
    Rectangle {
        id: grip
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 1
        height: 5
        color: grab.pressed || grab.containsMouse ? Theme.accent : "transparent"

        // Three pixels of texture so the strip reads as a handle rather than a
        // stray border (docs/DESIGN.md §2.3: draw a mark, never letter it).
        Row {
            anchors.centerIn: parent
            spacing: 3
            Repeater {
                model: 3
                Rectangle {
                    width: 3
                    height: 1
                    color: grab.pressed || grab.containsMouse ? Theme.bg : Theme.dim
                }
            }
        }

        MouseArea {
            id: grab
            anchors.fill: parent
            anchors.topMargin: -3
            anchors.bottomMargin: -3
            hoverEnabled: true
            cursorShape: Qt.SizeVerCursor
            preventStealing: true
            property real startY: 0
            property int startH: 0
            onPressed: function (m) {
                startY = mapToItem(null, m.x, m.y).y
                startH = box.boxHeight
            }
            onPositionChanged: function (m) {
                if (!pressed) return
                var dy = mapToItem(null, m.x, m.y).y - startY
                box.boxHeight = Math.max(box.minHeight,
                                         Math.min(box.maxHeight, Math.round(startH + dy)))
            }
            // Written on release, not on every pixel of the drag: a height is
            // one decision, not sixty file writes.
            onReleased: box.resized(box.boxHeight)
        }
    }
}
