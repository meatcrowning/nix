// NavHistory — the browser-style back/forward stack behind NavButtons,
// panel-side. Deliberate parallel copy of `apps/qmlcommon/NavHistory.qml` (see
// NavButtons.qml for why the two trees cannot share one file). Change one,
// change the other.
//
// The owner supplies `here` (a function returning the current location) and
// handles `navigate(state)`. Call `record()` just BEFORE moving somewhere new;
// going somewhere new drops the forward stack, exactly as a browser does.
//
// Both stacks are REASSIGNED rather than mutated in place: an in-place
// push()/pop() on a QML `var` array emits no change signal, so `canBack` /
// `canForward` and anything bound to them would silently go stale.
import QtQuick

QtObject {
    id: hist

    property var here: null
    signal navigate(var state)
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
