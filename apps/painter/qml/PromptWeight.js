.pragma library

// Shared by the main and region prompt editors. Keep the body selected so
// repeated shortcuts adjust the same group.
function isSeparator(t, i) {
    var c = t.charAt(i)
    return ",\n()|:".indexOf(c) >= 0 && !((c === "(" || c === ")") && i > 0 && t.charAt(i - 1) === "\\")
}
function tokenBounds(input) {
    var t = input.text, pos = input.cursorPosition, s = pos, e = pos
    while (s > 0 && !isSeparator(t, s - 1)) s--
    while (e < t.length && !isSeparator(t, e)) e++
    while (s < e && t.charAt(s) === " ") s++
    while (e > s && t.charAt(e - 1) === " ") e--
    return { start: s, end: e, ok: pos >= s && pos <= e }
}
function adjust(input, delta) {
    var t = input.text
    var s = input.selectionStart, e = input.selectionEnd
    if (s === e) {
        var b = tokenBounds(input)
        if (!b.ok || b.start === b.end) return false
        s = b.start; e = b.end
    }
    // Already inside a group? Its own bracket is the one to reuse. An
    // ESCAPED bracket is part of a tag's name and is not a group (§ the tag
    // completer), so it is skipped here too.
    var open = -1, closeAt = -1, weight = 1.0
    var i = s - 1
    while (i >= 0 && t.charAt(i) === " ") i--
    if (i >= 0 && t.charAt(i) === "(" && !(i > 0 && t.charAt(i - 1) === "\\")) {
        var after = t.substring(e)
        var m = /^\s*:\s*(-?\d*\.?\d+)\s*\)/.exec(after)
        var bare = /^\s*\)/.exec(after)
        if (m) { open = i; closeAt = e + m[0].length; weight = parseFloat(m[1]) }
        else if (bare) { open = i; closeAt = e + bare[0].length; weight = 1.0 }
    }
    var body = t.substring(s, e)
    if (body.trim() === "") return false
    var w = Math.round((weight + delta) * 100) / 100
    w = Math.max(-4, Math.min(4, w))
    var from = open >= 0 ? open : s
    var to = open >= 0 ? closeAt : e
    var out = (w === 1) ? body : "(" + body + ":" + w.toFixed(2) + ")"
    input.remove(from, to)
    input.insert(from, out)
    // The body stays selected, so the next press adjusts the same thing
    // rather than whatever the caret happens to be beside now.
    var at = from + (w === 1 ? 0 : 1)
    input.select(at, at + body.length)
    return true
}
