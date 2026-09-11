import QtQuick

// A DECISION, put to him as buttons — the `ask_choice` tool's card.
//
// [his, 2026-09-11] — "instead of just doing it and reporting back when its
// finished, what if they present the top available options to me? with format,
// track number, size, speed, etc displayed for each choice … at the bottom of
// that bubble itll show a row of buttons". The motivating job is a record with
// five Soulseek copies, but the card is generic: whatever the agent put in
// `details` is what the rows say.
//
// Three rules it exists to keep:
//
//   * AN AGENT IS WAITING BEHIND IT. The tool call is still open — his click is
//     what returns it — so the card says so while it waits (§10: the wait is
//     drawn) and says what happened once it stops waiting.
//   * ONCE ANSWERED IT IS OVER [his]: "once the user makes a selection they
//     shouldnt even be able to click another button in that bubble later". The
//     buttons STAY [his, 2026-09-11] — the one he took holds itself down and
//     the rest go dead beside it, so the card reads as the record of a decision
//     rather than losing the thing he was looking at. They are a READOUT then,
//     not an offer, which is why disabling rather than removing them is right
//     here (§10.1 forbids a control that looks live and does nothing — this one
//     does not look live). main.py's `_settle_choice` enforces the same thing
//     underneath, where a stray click cannot get around it.
//   * IT NEVER DEAD-ENDS. There is no `none of these` button [his,
//     2026-09-11]: the way out is the compose box he already has. While a card
//     is up, typing a reply settles it — his words go back as that tool call's
//     result (Root.send -> Ollama.answerChoiceText), so an agent that offered
//     five wrong copies can be told so in a sentence instead of being answered
//     with a shrug.
//
// API: `entry` (one `choiceAsked` object, with `state`/`index` kept current by
// `choiceSettled`), `picked(index)`, `declined()`.
Rectangle {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    property var entry: null

    signal picked(int index)

    readonly property var options: (entry && entry.options) ? entry.options : []
    readonly property string state_: (entry && entry.state) ? entry.state : "pending"
    readonly property bool pending: state_ === "pending"
    readonly property int chosen: (entry && entry.index !== undefined) ? entry.index : -1

    // A button is a button, not a paragraph: a candidate whose name runs long
    // (a folder path, a release with an edition in brackets) is cut here and
    // nowhere else — the numbered row above it says the whole thing.
    readonly property int labelMax: 28
    function buttonLabel(text) {
        var s = String(text || "");
        return s.length > labelMax ? s.slice(0, labelMax - 1) + "…" : s;
    }

    // What the card says once it has stopped waiting. Every branch names
    // itself: a card that simply went quiet would read as a broken control.
    readonly property string outcome: {
        if (pending) return "";
        if (chosen >= 0 && chosen < options.length)
            return "you picked " + (chosen + 1) + " · " + options[chosen].label;
        if (state_ === "replied") return "you answered in the box below";
        if (state_ === "declined") return "you picked none of these";
        if (state_ === "timeout") return "no answer — it went ahead without one";
        if (state_ === "cancelled") return "the turn was stopped before you answered";
        if (state_ === "expired") return "unanswered — that turn is over";
        return "no answer";
    }

    width: parent ? parent.width : 0
    implicitHeight: body.implicitHeight + 20
    height: implicitHeight
    radius: Theme.rounding
    // NO FILL [his, 2026-09-11]. The card already sits inside the reply's own
    // frame — under Plasma that is the KStyle's surface — and a second solid
    // slab on top of it was one panel too many (§5.1: the surface runs
    // unbroken; §4: a frame, not a stack of boxes).
    color: "transparent"
    border.width: Theme.ctrlBorder
    // Waiting on HIM is a state worth seeing from across the room (§3.5): the
    // frame carries the accent while it is open and goes quiet once it is not.
    border.color: root.pending ? Theme.accent : Theme.border

    Column {
        id: body
        x: 10
        y: 10
        width: parent.width - 20
        spacing: 6

        PixelText {
            width: parent.width
            wrapMode: Text.WordWrap
            text: (root.entry && root.entry.question) ? root.entry.question : "which one?"
            color: Theme.text
        }
        PixelText {
            width: parent.width
            wrapMode: Text.WordWrap
            visible: text !== ""
            text: (root.entry && root.entry.note) ? root.entry.note : ""
            color: Theme.textDim
        }

        Repeater {
            model: root.options

            delegate: Column {
                id: optionRow
                required property int index
                required property var modelData

                width: body.width
                spacing: 1

                readonly property bool isChosen: root.chosen === optionRow.index
                // Every `[name, value]` the agent gave, on one line. The names
                // are the agent's own words (format, size, speed, queue…) —
                // this draws them, it does not know them.
                readonly property string detailLine: {
                    var d = optionRow.modelData.details || [];
                    var parts = [];
                    for (var i = 0; i < d.length; i++) {
                        var name = d[i][0] || "";
                        var value = d[i][1] || "";
                        parts.push(name === "" ? value : name + " " + value);
                    }
                    return parts.join("  ·  ");
                }

                PixelText {
                    width: parent.width
                    elide: Text.ElideRight
                    text: (optionRow.index + 1) + ".  " + optionRow.modelData.label
                    // The one he took is the one worth finding again later.
                    color: optionRow.isChosen ? Theme.accent
                         : root.pending ? Theme.text : Theme.textDim
                }
                PixelText {
                    x: 18
                    width: parent.width - 18
                    wrapMode: Text.WordWrap
                    visible: text !== ""
                    text: optionRow.detailLine
                    color: Theme.textDim
                }
                PixelText {
                    x: 18
                    width: parent.width - 18
                    wrapMode: Text.WordWrap
                    visible: text !== ""
                    text: optionRow.modelData.note || ""
                    color: Theme.dim
                }
            }
        }

        // The buttons ARE the candidates [his, 2026-09-11]: each one wears the
        // option's own name, so pressing it is picking that thing rather than
        // picking a number and trusting the list above to still mean what it
        // did (§10.1 — the control's label is its effect). A long name is
        // clipped for the button only; the row above carries it in full.
        // They outlive the answer — held down for the one he took, dead for
        // the rest.
        // ONE LINE, WHATEVER THE COUNT [his, 2026-09-11]: the row divides the
        // card's width between the candidates rather than wrapping into a
        // block of buttons. Each button then elides its own name — the
        // numbered row above it carries the full one.
        Row {
            id: verbRow
            width: parent.width
            spacing: 6
            readonly property int cells: Math.max(1, root.options.length)
            readonly property int cellW:
                Math.max(40, Math.floor((width - spacing * (cells - 1)) / cells))

            Repeater {
                model: root.options
                delegate: JobVerb {
                    required property int index
                    required property var modelData
                    width: verbRow.cellW
                    label: root.buttonLabel(modelData.label)
                    enabled: root.pending
                    lit: root.chosen === index
                    onClicked: root.picked(index)
                }
            }
        }

        // The wait — and, for an ending no button can show, what came of it.
        // A pressed button IS the answer, so it is not narrated twice (§3.5
        // says a state twice only where the first reading can be missed).
        PixelText {
            width: parent.width
            wrapMode: Text.WordWrap
            visible: text !== ""
            // While it waits, the line says BOTH ways out — press one, or say
            // something. A pressed button is its own answer afterwards (§3.5),
            // so only an ending no button can show is spelled out.
            text: root.pending ? "waiting for you… or answer in the box below"
                : (root.chosen >= 0) ? ""
                : root.outcome
            color: Theme.textDim
        }
    }
}
