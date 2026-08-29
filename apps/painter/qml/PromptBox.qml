import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

Rectangle {
    id: box
    property string placeholder: ""
    property bool negative: false
    signal edited(string text)

    // ------------------------------------------------------ tag completion
    //: The scene's one `TagPopup` (see Root.qml), and whether this family's
    //: prompt is written in Danbooru tags at all. On a prose family — Krea's
    //: `<think>` paragraphs, a video shot description — a tag list popping up
    //: mid-sentence is noise, so the whole feature is off there rather than
    //: merely unhelpful.
    property Item tagPopup: null
    property bool tagsEnabled: false
    readonly property bool tagsOn: box.tagsEnabled && box.tagPopup !== null
                                   && typeof Tags !== "undefined" && Tags && Tags.available
    //: The last query sent, so an unchanged one does not reset the highlighted
    //: row under him while he is arrowing through it.
    property string lastQuery: ""
    //: WHERE THE CARET WAS LEFT BY AN INSERTION. Completing writes the tag and
    //: its comma, which is a text change like any other — and re-completing the
    //: word that was just accepted would reopen the list on top of itself. A
    //: POSITION rather than a flag: any key at all moves the caret off it, so
    //: this cannot swallow the next query the way a "skip one refresh" flag did
    //: (the refresh it skipped was whichever came first, which was sometimes
    //: the next word he typed).
    property int skipAt: -1

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
        box.closeCompletion()
    }
    // The editor's own text, for callers that want to read it back.
    readonly property alias text: input.text

    //: THE TAG UNDER THE CARET. A prompt is comma-separated tags, weight groups
    //: and (on Anima) the odd natural-language clause, so the token is whatever
    //: lies between the nearest separators — and the caret has to be INSIDE it,
    //: or "1girl, " with the caret after the space would offer completions for
    //: the tag before it.
    function tokenBounds() {
        var t = input.text, pos = input.cursorPosition;
        var s = pos, e = pos;
        while (s > 0 && !box.isSeparator(t, s - 1)) s--;
        while (e < t.length && !box.isSeparator(t, e)) e++;
        while (s < e && t.charAt(s) === " ") s++;
        while (e > s && t.charAt(e - 1) === " ") e--;
        var ok = pos >= s && pos <= e;
        return { start: s, end: e, ok: ok, word: ok ? t.substring(s, e) : "" };
    }

    //: Where one tag ends and the next begins. An ESCAPED bracket is not one
    //: of them: `rebecca \(cyberpunk\)` is a single tag whose name carries its
    //: series, and treating its bracket as a separator would complete the word
    //: `cyber` instead of the character.
    function isSeparator(t, i) {
        var c = t.charAt(i);
        if (",\n()|:".indexOf(c) < 0) return false;
        if ((c === "(" || c === ")") && i > 0 && t.charAt(i - 1) === "\\") return false;
        return true;
    }

    //: What is offered for it — or nothing, which is most of the time. ONE
    //: character is enough, the way every tag completer people already use
    //: works: the list is ordered by post count, so the first letter's answer
    //: is the tag you meant more often than not. A clause is still left alone —
    //: a full stop or more than four words is prose, exactly as
    //: `boorutags.check` reads it.
    function completionQuery() {
        if (!box.tagsOn || !input.activeFocus) return "";
        var b = box.tokenBounds();
        if (!b.ok) return "";
        var w = b.word.replace(/^@/, "").replace(/\\/g, "").trim();
        if (w.length < 1 || w.indexOf(".") >= 0 || w.split(" ").length > 4) return "";
        return w;
    }

    //: Is this tag already in the box? Drawn dim if it is — the thing every
    //: good tag completer does, because the list is most useful when it says
    //: what you have NOT got yet.
    function hasTag(tag) {
        var want = String(tag).replace(/_/g, " ").toLowerCase();
        var parts = input.text.toLowerCase().replace(/\\/g, "").split(/[,\n]/);
        for (var i = 0; i < parts.length; i++) {
            var p = parts[i].replace(/_/g, " ").replace(/^[\s(@]+/, "")
                            .replace(/[\s)]+$/, "").split(":")[0].trim();
            if (p === want) return true;
        }
        return false;
    }

    function refreshCompletion() {
        if (!box.tagsOn) return;
        if (input.cursorPosition === box.skipAt) { box.closeCompletion(); return }
        box.skipAt = -1;
        var q = box.completionQuery();
        if (q === "") { box.closeCompletion(); return }
        var rows = Tags.complete(q, 10);
        if (!rows || rows.length === 0) { box.closeCompletion(); return }
        var items = [];
        for (var i = 0; i < rows.length; i++)
            items.push({ tag: rows[i].tag, alias: rows[i].alias,
                         category: rows[i].category, posts: rows[i].posts,
                         insert: rows[i].insert, have: box.hasTag(rows[i].tag),
                         trigger: (function (e) { return function () { box.insertTag(e) } })(rows[i]) });
        // ANCHORED AT THE TAG, NOT AT THE CARET. A list that re-aims itself one
        // character to the right on every keystroke is the single thing that
        // makes a completer feel cheap; anchored where the word starts it sits
        // still while the word is typed.
        var b2 = box.tokenBounds();
        var r = input.positionToRectangle(b2.ok ? b2.start : input.cursorPosition);
        var p = input.mapToItem(null, r.x, r.y);
        box.lastQuery = q;
        box.tagPopup.open(p.x, p.y, items, r.height);
    }

    function closeCompletion() {
        box.lastQuery = "";
        if (box.tagPopup && box.tagPopup.visible) box.tagPopup.close();
    }

    //: Whether the popup on screen belongs to THIS box — there is one of them
    //: and two of these, and the keys must only be taken by the one being typed
    //: in.
    function completionMine() {
        return box.tagsOn && box.tagPopup.visible && input.activeFocus
    }

    //: Replace the token with the tag, spelled the way it will be SENT
    //: (`graph.spell_tag`, the same function the transform uses), and put the
    //: comma in — a tag list is comma-separated and typing the separator by
    //: hand after every completion is the thing being automated.
    function insertTag(entry) {
        var b = box.tokenBounds();
        if (!b.ok) return;
        var ins = entry.insert;
        var tail = input.text.substring(b.end);
        // THE COMMA COMES WITH THE TAG. A tag list is comma-separated and
        // typing the separator after every completion is the thing being
        // automated [his, 2026-08-28] — so a completion ends `tag, ` and the
        // caret is already in the next tag.
        //
        // Two tails take no comma, because in both one is already there or
        // would be wrong: a comma already following, and a weight or a closing
        // bracket (`:1.2` / `)` — the token ends at the colon, so this is
        // `(lowres` inside a group). EVERYTHING ELSE, end of line included,
        // gets the comma AND the space: the newline case used to take the comma
        // alone, on the reasoning that nothing should trail a line, and what
        // that actually produced was a completion with no space after its comma
        // [his, 2026-08-28, twice].
        if (/^\s*[,:)]/.test(tail)) { /* already separated */ }
        else ins += ", ";
        input.remove(b.start, b.end);
        input.insert(b.start, ins);
        input.cursorPosition = b.start + ins.length;
        box.skipAt = input.cursorPosition;
        box.closeCompletion();
    }

    //: The index costs ~0.6s to build, once, on a worker thread — started when
    //: a box that WANTS completions takes the keyboard, so a session that never
    //: types an Anima prompt never pays for it.
    Connections {
        target: (typeof Tags !== "undefined" && Tags) ? Tags : null
        function onReadyChanged() { box.refreshCompletion() }
    }

    Timer {
        id: completeSoon
        // JUST ENOUGH TO COALESCE ONE KEYSTROKE's text change with its cursor
        // move, and no more. This was 80ms — a tenth of a second between the
        // letter and the list, which is exactly what makes a completer feel
        // sluggish; the query itself is 1-4ms against the index.
        interval: 12
        onTriggered: box.refreshCompletion()
    }

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
    radius: Theme.rounding
    border.color: input.activeFocus ? Theme.accent : Theme.border
    border.width: Theme.ctrlBorder

    KineticFlickable {
        id: flick
        anchors.fill: parent
        anchors.margins: 5
        anchors.bottomMargin: 7          // clear of the grab strip
        contentWidth: width - vbar.barW
        contentHeight: input.height
        clip: true
        ScrollBar.vertical: VScroll { id: vbar }

        TextEdit {
            id: input
            // NOT the full viewport: an attached ScrollBar OVERLAYS the
            // flickable, so text laid out to `flick.width` runs underneath
            // the bar and the tail of every wrapped line sits behind it. The
            // gutter is reserved unconditionally, as the gallery grid does,
            // so the wrap does not reflow the moment the box starts to
            // scroll.
            width: flick.width - vbar.barW
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
            onTextChanged: {
                if (!box.syncing) box.edited(text);
                if (box.tagsOn) completeSoon.restart();
            }
            onCursorPositionChanged: if (box.tagsOn) completeSoon.restart()
            onActiveFocusChanged: {
                if (activeFocus) { if (box.tagsOn) Tags.prepare() }
                else box.closeCompletion();
            }
            // Ctrl+Enter belongs to the window, not the editor.
            //
            // AND WHILE THE TAG LIST IS OPEN it owns the four keys a list owns:
            // up/down walk it, Tab and Return take the highlighted row. Escape
            // is NOT here — a window-level `Shortcut` sees a key before any
            // focused item does (Root.qml), so closing the list on Escape has
            // to be the first branch of the window's own chain or it would
            // release the box instead.
            Keys.onPressed: function (e) {
                if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                        && (e.modifiers & Qt.ControlModifier)) {
                    e.accepted = false
                    return
                }
                if (!box.completionMine()) return
                if (e.key === Qt.Key_Down) { box.tagPopup.move(1); e.accepted = true }
                else if (e.key === Qt.Key_Up) { box.tagPopup.move(-1); e.accepted = true }
                else if (e.key === Qt.Key_Tab
                         || e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
                    box.tagPopup.accept()
                    e.accepted = true
                }
            }
            // Escape LETS GO of the box — the one thing it is for here. Handled
            // on the editor as well as at the window, because a focused text
            // item is exactly where a window-level Shortcut is least reliable.
            //
            // BOTH OF THEM RUN, measured: the window's `Shortcut` fires and the
            // key still reaches this handler. That is invisible while the two
            // agree (they both release the box) and it is exactly the bug when
            // they do not — the shortcut closes the tag list, this one then
            // sees no list and lets go of the box he is still typing in. So an
            // Escape that DISMISSED a list is spent, whichever of the two got
            // to it first: `justClosed` is true for the rest of this event.
            Keys.onEscapePressed: function (e) {
                if (box.tagsOn && (box.tagPopup.visible || box.tagPopup.justClosed)) {
                    box.closeCompletion()
                    e.accepted = true
                    return
                }
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
