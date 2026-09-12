import QtQuick

// A DECISION, put to him as a list he can press — the `ask_choice` tool's card.
//
// [his, 2026-09-11] — "instead of just doing it and reporting back when its
// finished, what if they present the top available options to me? with format,
// track number, size, speed, etc displayed for each choice … at the bottom of
// that bubble itll show a row of buttons". The row of buttons is gone [his,
// 2026-09-12] — "i want each entire block of the details of the selections to
// serve as its own selection bubble" — so the candidate block IS the control.
// The motivating job is a record with five Soulseek copies, but the card is
// generic: whatever the agent put in `details` is what the rows say.
//
// Three rules it exists to keep:
//
//   * AN AGENT IS WAITING BEHIND IT. The tool call is still open — his click is
//     what returns it — so the card says so while it waits (§10: the wait is
//     drawn) and says what happened once it stops waiting.
//   * ONCE ANSWERED IT IS OVER [his]: "once the user makes a selection they
//     shouldnt even be able to click another button in that bubble later". The
//     candidates STAY [his, 2026-09-11] — the one he took keeps its highlight
//     and accent gutter and the rest go quiet beside it, so the card reads as
//     the record of a decision rather than losing the thing he was looking at.
//     They are a READOUT then, not an offer, which is why they stop hovering
//     and stop showing the hand cursor (§10.1 forbids a control that looks live
//     and does nothing — this one does not look live). main.py's
//     `_settle_choice` enforces the same thing underneath, where a stray click
//     cannot get around it.
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

            // THE WHOLE BLOCK IS THE BUTTON [his, 2026-09-12] — "i want each
            // entire block of the details of the selections to serve as its own
            // selection bubble", and it LOOKS like one [his, same day: "can you
            // make them look like actual buttons just larger than normal"], so
            // it is a real relief cell grown to hold the candidate rather than
            // a hover highlight on a paragraph (ChoiceBlock.qml, with its
            // KStyle twin under Plasma). There is no row of buttons under the
            // card any more: the thing he is reading IS the thing he presses,
            // which is §10.1 taken to its end — the control's label is the
            // whole candidate, format, size, speed and all, so nothing is
            // clipped to fit a button.
            delegate: ChoiceBlock {
                id: optionRow
                required property int index
                required property var modelData

                // The block IS the button, so it answers a button's questions:
                // `label`, `face`, `lit` and `enabled` are what the selftest
                // reads off the item tree to prove what is drawn and what is
                // still live (main.py's `_card_verbs`, tools/choice-test.py).
                readonly property string label: String(modelData.label || "")
                readonly property bool isChosen: root.chosen === optionRow.index
                lit: isChosen
                enabled: root.pending
                width: body.width

                onClicked: root.picked(optionRow.index)

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

                Column {
                    width: parent.width
                    spacing: 1

                    PixelText {
                        width: parent.width
                        elide: Text.ElideRight
                        text: (optionRow.index + 1) + ".  " + optionRow.modelData.label
                        // The one he took is the one worth finding again later.
                        color: optionRow.isChosen ? Theme.accent : optionRow.fg
                    }
                    PixelText {
                        x: 18
                        width: parent.width - 18
                        wrapMode: Text.WordWrap
                        visible: text !== ""
                        text: optionRow.detailLine
                        color: optionRow.fgDim
                    }
                    PixelText {
                        x: 18
                        width: parent.width - 18
                        wrapMode: Text.WordWrap
                        visible: text !== ""
                        text: optionRow.modelData.note || ""
                        color: optionRow.fgFaint
                    }
                }
            }
        }

        // The wait — and, for an ending the list cannot show, what came of it.
        // The held candidate IS the answer, so it is not narrated twice (§3.5
        // says a state twice only where the first reading can be missed).
        PixelText {
            width: parent.width
            wrapMode: Text.WordWrap
            visible: text !== ""
            // While it waits, the line says BOTH ways out — press one, or say
            // something. The held candidate is its own answer afterwards
            // (§3.5), so only an ending the list cannot show is spelled out.
            text: root.pending ? "waiting for you… or answer in the box below"
                : (root.chosen >= 0) ? ""
                : root.outcome
            color: Theme.textDim
        }
    }
}
