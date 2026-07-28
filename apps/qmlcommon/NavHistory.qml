// NavHistory — the browser-style back/forward stack behind NavButtons.
//
// The owner supplies `here` (a function returning the current location as a
// plain value) and handles the `navigate(state)` signal. Call `record()` just
// BEFORE moving somewhere new; going somewhere new drops the forward stack,
// exactly as a browser does.
//
//     NavHistory {
//         id: hist
//         here: function () { return view.path; }
//         onNavigate: function (s) { view.apply(s); }
//     }
//
// Both stacks are REASSIGNED rather than mutated in place. An in-place
// `push()`/`pop()` on a QML `var` array emits no change signal, so `canBack` /
// `canForward` — and any titlebar button or menu item bound to them — silently
// go stale. (player's hand-rolled stack had exactly that shape; it only got
// away with it because nothing was bound to it.)
import QtQuick

QtObject {
    id: hist

    // function () -> state. Whatever shape the owner likes; NavHistory never
    // inspects it, it only hands it back.
    property var here: null

    // Emitted with a previously recorded state that the owner must now restore.
    signal navigate(var state)

    // Cap, so a long session cannot grow the stack without bound.
    property int limit: 50

    property var backStack: []
    property var forwardStack: []

    readonly property bool canBack: backStack.length > 0
    readonly property bool canForward: forwardStack.length > 0

    function _here() { return here ? here() : null; }

    function record() {
        var b = backStack.concat([_here()]);
        if (b.length > limit)
            b = b.slice(b.length - limit);
        backStack = b;
        forwardStack = [];
    }

    function back() {
        if (backStack.length === 0)
            return false;
        var b = backStack.slice();
        var s = b.pop();
        forwardStack = forwardStack.concat([_here()]);
        backStack = b;
        hist.navigate(s);
        return true;
    }

    function forward() {
        if (forwardStack.length === 0)
            return false;
        var f = forwardStack.slice();
        var s = f.pop();
        backStack = backStack.concat([_here()]);
        forwardStack = f;
        hist.navigate(s);
        return true;
    }

    function clear() {
        backStack = [];
        forwardStack = [];
    }
}
