import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// A lossless view over a comma-separated prompt. Tags are movable; the bytes
// between their slots are not. Consequently merely visiting this view cannot
// reflow, trim, or otherwise rewrite the editor's text.
Item {
    id: pills
    objectName: negative ? "negativePromptPills" : "positivePromptPills"
    property string value: ""
    property bool negative: false
    signal edited(string text)

    property var tags: []                 // { id, raw }, in display order
    property var separators: []           // prefix, gaps, suffix (tags + 1)
    property int nextId: 1
    property bool syncing: false
    property int editingId: -1
    property int dragId: -1
    property int dropSlot: -1

    function parse(text) {
        var pieces = [], cuts = [], out = [], i = 0, start = 0
        var parenDepth = 0, bracketDepth = 0
        function escapedAt(at) {
            var slashes = 0
            for (var q = at - 1; q >= 0 && text.charAt(q) === "\\"; q--) slashes++
            return (slashes % 2) === 1
        }
        for (; i < text.length; i++) {
            var c = text.charAt(i), escaped = escapedAt(i)
            if (!escaped && c === "(") parenDepth++
            else if (!escaped && c === ")" && parenDepth > 0) parenDepth--
            else if (!escaped && c === "[") bracketDepth++
            else if (!escaped && c === "]" && bracketDepth > 0) bracketDepth--
            var cut = (c === "\n" || c === "\r" || c === ",")
                      && parenDepth === 0 && bracketDepth === 0
            if (!cut) continue
            pieces.push(text.substring(start, i))
            var s = i++
            if (c === "\r" && i < text.length && text.charAt(i) === "\n") i++
            while (i < text.length && /[ \t\r\n]/.test(text.charAt(i))) i++
            cuts.push(text.substring(s, i)); start = i; i--
        }
        pieces.push(text.substring(start))

        // Whitespace at a pill's edges is formatting, not part of the thing
        // being moved. Fold it into the adjacent fixed slot so moving a final
        // tag cannot carry its trailing spaces into the middle of the prompt.
        var seps = [""]
        for (var p = 0; p < pieces.length; p++) {
            var raw = pieces[p]
            var lm = /^\s*/.exec(raw)[0]
            var rm = /\s*$/.exec(raw.substring(lm.length))[0]
            var bodyEnd = raw.length - rm.length
            out.push({ id: pills.nextId++, raw: raw.substring(lm.length, bodyEnd) })
            seps[p] += lm
            seps.push((p < cuts.length ? cuts[p] : "") + rm)
        }
        pills.tags = out
        pills.separators = seps
        pills.rebuildDisplay()
    }

    function serialize() {
        var s = pills.separators.length ? pills.separators[0] : ""
        for (var i = 0; i < pills.tags.length; i++)
            s += pills.tags[i].raw + pills.separators[i + 1]
        return s
    }

    onValueChanged: {
        if (syncing || value === serialize()) return
        editingId = -1; dragId = -1; dropSlot = -1
        parse(value)
    }
    Component.onCompleted: parse(value)

    function commit() {
        var s = serialize()
        // `value` is bound to the generation model. Never assign it here: that
        // would sever the binding. The ordinary PromptBox edit path writes the
        // model, whose notification echoes the new value back into this view.
        edited(s)
    }

    function rebuildDisplay() {
        var d = []
        for (var i = 0; i < tags.length; i++) {
            if (i > 0 && /[\r\n]/.test(separators[i] || "")) {
                var nl = (String(separators[i]).match(/\r\n|\r|\n/g) || []).length
                d.push({ kind: "break", key: "break-" + i,
                         lines: Math.max(1, nl) })
            }
            d.push({ kind: "tag", key: "tag-" + tags[i].id,
                     tagId: tags[i].id, raw: tags[i].raw })
        }
        d.push({ kind: "add", key: "add" })
        displayModel = d
    }
    property var displayModel: []

    function tagIndex(id) {
        for (var i = 0; i < tags.length; i++) if (tags[i].id === id) return i
        return -1
    }
    function replaceTag(id, raw) {
        var a = tags.slice(), i = tagIndex(id)
        if (i < 0) return
        a[i] = { id: a[i].id, raw: raw }; tags = a
        editingId = -1; rebuildDisplay(); commit()
    }
    function removeTag(id) {
        var a = tags.slice(), s = separators.slice(), i = tagIndex(id)
        if (i < 0) return
        a.splice(i, 1)
        // Prefer the following separator; for the final pill consume the one
        // before it. This is the only operation which intentionally changes
        // layout, because deleting content must also close the resulting hole.
        if (i + 1 < a.length + 1) s.splice(i + 1, 1)
        else if (i > 0) s.splice(i, 1)
        if (!a.length) { a = [{ id: nextId++, raw: "" }]; s = ["", ""] }
        tags = a; separators = s; rebuildDisplay(); commit()
    }
    function moveTag(id, slot) {
        var a = tags.slice(), from = tagIndex(id)
        if (from < 0) return
        var one = a.splice(from, 1)[0]
        if (slot > from) slot--
        slot = Math.max(0, Math.min(a.length, slot))
        a.splice(slot, 0, one); tags = a
        dragId = -1; dropSlot = -1; rebuildDisplay(); commit()
    }

    function addTag() {
        if (tags.length === 1 && tags[0].raw === "" && serialize().trim() === "") {
            editingId = tags[0].id
            return
        }
        var a = tags.slice(), s = separators.slice()
        // Match the separator beside the insertion when it is a simple comma;
        // a newline is an intentional group boundary and is never invented.
        var join = ", "
        for (var i = s.length - 1; i > 0; i--)
            if (/^,[ \t]*$/.test(s[i])) { join = s[i]; break }
        s.splice(s.length - 1, 0, join)
        var id = nextId++
        a.push({ id: id, raw: "" })
        tags = a; separators = s; rebuildDisplay(); editingId = id
    }

    function chooseDrop(sceneX, sceneY) {
        var slot = tags.length, bestRow = 1e9
        for (var i = 0; i < rep.count; i++) {
            var q = rep.itemAt(i)
            if (!q || q.kind !== "tag" || q.tagId === dragId) continue
            var p = q.mapToItem(null, q.width / 2, q.height / 2)
            var row = Math.abs(sceneY - p.y)
            if (row < bestRow - q.height / 2) { bestRow = row; slot = q.tagSlot }
            if (row <= bestRow + q.height / 2) {
                bestRow = Math.min(bestRow, row)
                if (sceneY < p.y - q.height / 2 || sceneX < p.x) slot = q.tagSlot
                else slot = q.tagSlot + 1
            }
        }
        dropSlot = slot
        placeMarker()
    }

    function placeMarker() {
        marker.visible = dragId >= 0 && dropSlot >= 0
        if (!marker.visible) return
        var wanted = null, tagNo = 0
        for (var i = 0; i < rep.count; i++) {
            var q = rep.itemAt(i)
            if (!q || q.kind !== "tag") continue
            if (tagNo === dropSlot) { wanted = q; break }
            tagNo++
        }
        if (!wanted) {
            for (var j = rep.count - 1; j >= 0; j--) {
                var last = rep.itemAt(j)
                if (last && last.kind === "tag") { wanted = last; break }
            }
            if (!wanted) return
            var ep = wanted.mapToItem(viewport, wanted.width + 2, 0)
            marker.x = ep.x; marker.y = ep.y; marker.height = wanted.height
        } else {
            var bp = wanted.mapToItem(viewport, -2, 0)
            marker.x = bp.x; marker.y = bp.y; marker.height = wanted.height
        }
    }

    KineticFlickable {
        id: flick
        anchors.fill: parent
        anchors.margins: 5
        anchors.bottomMargin: 7
        contentWidth: width
        contentHeight: flow.implicitHeight
        clip: true
        ScrollBar.vertical: VScroll { }

        Item {
            id: viewport
            width: flick.width
            height: flow.implicitHeight

            Flow {
                id: flow
                width: parent.width
                spacing: 4

                Repeater {
                    id: rep
                    model: pills.displayModel
                    delegate: Item {
                        id: cell
                        required property var modelData
                        readonly property string kind: modelData.kind
                        readonly property int tagId: kind === "tag" ? modelData.tagId : -1
                        readonly property int tagSlot: kind === "tag" ? pills.tagIndex(tagId) : -1
                        width: kind === "break" ? flow.width
                             : kind === "add" ? addButton.implicitWidth : chip.implicitWidth
                        height: kind === "break"
                                ? 2 + (Math.max(1, modelData.lines) - 1) * (Theme.lineHeight + 4)
                                : kind === "add" ? addButton.implicitHeight : chip.implicitHeight

                        Rectangle {
                            id: chip
                            visible: cell.kind === "tag"
                            width: implicitWidth
                            height: implicitHeight
                            implicitWidth: Math.min(flow.width,
                                Math.max(28, label.implicitWidth + 8 + 6 + 14))
                            implicitHeight: Math.max(Theme.lineHeight + 4, label.implicitHeight + 4)
                            color: hover.hovered ? Theme.highlight : Theme.bgAlt
                            border.width: 1
                            border.color: pills.dragId === cell.tagId ? Theme.accent : Theme.border
                            radius: Theme.rounding

                            PixelText {
                                id: label
                                anchors.left: parent.left
                                anchors.leftMargin: 8
                                anchors.right: remove.left
                                anchors.rightMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                elide: Text.ElideRight
                                text: String(cell.modelData.raw).trim() || "..."
                                color: pills.negative ? Theme.textDim : Theme.text
                                visible: pills.editingId !== cell.tagId
                            }
                            TextInput {
                                id: edit
                                anchors.left: parent.left
                                anchors.leftMargin: 8
                                anchors.right: remove.left
                                anchors.rightMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                visible: pills.editingId === cell.tagId
                                text: cell.kind === "tag" ? String(cell.modelData.raw) : ""
                                color: pills.negative ? Theme.textDim : Theme.text
                                font: (typeof DeskStyle !== "undefined" && DeskStyle
                                       && typeof DeskStyle.editorFontForScale === "function")
                                      ? DeskStyle.editorFontForScale(Screen.devicePixelRatio)
                                      : Theme.editorFontForScale(Screen.devicePixelRatio)
                                selectByMouse: true
                                onVisibleChanged: if (visible) { forceActiveFocus(); selectAll() }
                                Keys.onReturnPressed: pills.replaceTag(cell.tagId, text)
                                Keys.onEnterPressed: pills.replaceTag(cell.tagId, text)
                                Keys.onEscapePressed: pills.editingId = -1
                                onActiveFocusChanged: if (!activeFocus && visible)
                                                          pills.replaceTag(cell.tagId, text)
                            }
                            TextButton {
                                id: remove
                                z: 2
                                anchors.right: parent.right
                                anchors.rightMargin: 2
                                anchors.verticalCenter: parent.verticalCenter
                                width: 14
                                label: "x"
                                tone: Theme.crit
                                visible: hover.hovered && pills.editingId !== cell.tagId
                                onClicked: pills.removeTag(cell.tagId)
                            }
                            HoverHandler { id: hover }
                            Item { id: proxy; visible: false }
                            MouseArea {
                                id: dragger
                                z: 1
                                anchors.fill: parent
                                anchors.rightMargin: remove.visible ? remove.width + 2 : 0
                                preventStealing: true
                                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                property real pressSceneX: 0
                                property real pressSceneY: 0
                                property bool dragging: false
                                onPressed: function(m) {
                                    var p = mapToItem(null, m.x, m.y)
                                    pressSceneX = p.x; pressSceneY = p.y; dragging = false
                                }
                                onPositionChanged: function(m) {
                                    if (!pressed) return
                                    var p = mapToItem(null, m.x, m.y)
                                    var dx = p.x - pressSceneX, dy = p.y - pressSceneY
                                    if (!dragging && Math.sqrt(dx*dx + dy*dy) < 10) return
                                    dragging = true; pills.dragId = cell.tagId
                                    pills.chooseDrop(p.x, p.y)
                                }
                                onReleased: function(m) {
                                    if (dragging) pills.moveTag(cell.tagId, pills.dropSlot)
                                    dragging = false
                                }
                                onCanceled: { dragging = false; pills.dragId = -1; pills.dropSlot = -1 }
                                onDoubleClicked: { if (!dragging) pills.editingId = cell.tagId }
                            }
                        }
                        TextButton {
                            id: addButton
                            visible: cell.kind === "add"
                            label: "[ + ]"
                            tone: Theme.textDim
                            onClicked: pills.addTag()
                        }
                    }
                }
            }

            Rectangle {
                id: marker
                visible: false
                width: 2
                color: Theme.accent
            }
        }
    }
}
