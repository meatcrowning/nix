import QtQuick

Canvas {
    id: bands
    required property var editor
    required property var viewport
    property var boundaries: []
    property var colours: []
    property bool marked: false
    property var highlighted: []
    property color highlightColor: editor.selectionColor
    onHighlightedChanged: requestPaint()
    onHighlightColorChanged: requestPaint()
    objectName: "tokenBands"
    z: -1
    width: editor.width
    y: Math.max(0, viewport.contentY)
    height: Math.max(0, Math.min(viewport.height, editor.height - y))
    onYChanged: requestPaint()
    onBoundariesChanged: requestPaint()
    onColoursChanged: requestPaint()
    onMarkedChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    FontMetrics { id: metrics; font: bands.editor.font }
    Connections {
        target: bands.editor
        function onTextChanged() { bands.requestPaint() }
        function onFontChanged() { bands.requestPaint() }
        function onSelectionStartChanged() { bands.requestPaint() }
        function onSelectionEndChanged() { bands.requestPaint() }
    }
    onPaint: {
        var ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        if ((!marked && !highlighted.length) || colours.length !== 2) return
        var text = editor.text, token = 0
        // Follow the real editor's cursor geometry, including soft wraps and
        // surrogate pairs. Paint under its glyphs and native selection.
        for (var i = Math.max(0, editor.positionAt(0, y)); i < text.length;) {
            while (token < boundaries.length && i >= boundaries[token]) token++
            var n = text.charCodeAt(i) >= 0xd800 && text.charCodeAt(i) <= 0xdbff ? 2 : 1
            var character = text.substr(i, n)
            var selected = i < editor.selectionEnd && i + n > editor.selectionStart
            if (!selected && character !== "\n" && character !== "\r") {
                var start = editor.positionToRectangle(i)
                if (start.y > bands.y + height) break
                var end = editor.positionToRectangle(i + n)
                var sameLine = Math.abs(start.y - end.y) < 1
                var span = sameLine ? Math.abs(end.x - start.x) : metrics.advanceWidth(character)
                var x = sameLine ? Math.min(start.x, end.x) : start.x
                var active = highlighted.some(function(r) { return i >= r.start && i < r.end })
                ctx.fillStyle = active ? Qt.rgba(highlightColor.r, highlightColor.g, highlightColor.b, 0.38) : marked ? colours[token % 2] : "transparent"
                ctx.fillRect(x, start.y - bands.y, span, start.height)
            }
            i += n
        }
    }
}
