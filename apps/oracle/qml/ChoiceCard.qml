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
//     buttons are not disabled, they are GONE, replaced by the line saying what
//     he picked — a dead control is not drawn at all (§10.1), and main.py's
//     `_settle_choice` enforces the same thing where it cannot be got around.
//   * IT NEVER DEAD-ENDS. `none of these` is always there, because an agent
//     that offered five wrong candidates must not be answerable only by waiting
//     out the timeout.
//
// API: `entry` (one `choiceAsked` object, with `state`/`index` kept current by
// `choiceSettled`), `picked(index)`, `declined()`.
Rectangle {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    property var entry: null

    signal picked(int index)
    signal declined()

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
    color: Theme.bgAlt
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

        // The buttons, while there is something to press. `pick 1` rather than
        // a bare `1`: a control says what it does (§10.1), and the number is
        // the row above it.
        Flow {
            width: parent.width
            spacing: 6
            visible: root.pending

            Repeater {
                model: root.options
                delegate: JobVerb {
                    required property int index
                    label: "pick " + (index + 1)
                    onClicked: root.picked(index)
                }
            }
            JobVerb {
                label: "none of these"
                onClicked: root.declined()
            }
        }

        // The wait, and then what came of it — never a card that just stops.
        PixelText {
            width: parent.width
            wrapMode: Text.WordWrap
            text: root.pending ? "waiting for you…" : root.outcome
            color: root.pending ? Theme.textDim
                 : (root.chosen >= 0 ? Theme.text : Theme.textDim)
        }
    }
}
