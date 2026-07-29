#!/usr/bin/env python3
"""boardctl — move an item on `docs/board.md` without hand-editing it.

The board is a markdown file (`apps/board/AGENTS.md`), and until this existed
the only ways to move an item on it were the GUI, which deliberately never moves
anything, and a text editor, which is how half-written rows and reflowed tables
happen. This is the third way, and it is the one an agent should use:

    boardctl.py start 4 --where 'apps/player/**'   # NEEDS YOU -> IN FLIGHT
    boardctl.py land 'cover art' --commit a3c2aac --what 'player: dim the art'
    boardctl.py land --commit a3c2aac --what 'player: dim the art'   # no row
    boardctl.py back 'cover art' --why 'FAILED: **cover art** - blocked on FOCUS'
    boardctl.py stall 'board app'                  # a row nothing owns -> to-do
    boardctl.py note 'PARTIAL: **Relaunch `player`** - live source, no hot reload.'
    boardctl.py note 'COMPLETION: **the fade** - landed.' \\
                     'PARTIAL: **the tooltip** - needs a rebuild.'   # TWO items
    boardctl.py list

    boardctl.py agents                             # who is running, by phase
    boardctl.py inbox take                         # HIS notes to you, mid-flight
    boardctl.py inbox send 'also fix the tooltip' --to Marbas # or --to <agent id>

The orchestrator's verbs — how one sentence he typed becomes several agents
(`../boardwork.py` is the mechanism and the authority):

    boardctl.py dispatch 'wire FOCUS through vtbclient' --where 'apps/pylib/**'
    boardctl.py ask 'How far should the fade reach?' --option 'apps only' \\
        --option 'apps and panel' --if-unanswered 'the apps get it, nothing else'
    boardctl.py cap 6                              # workers allowed at once
    boardctl.py phase coding --doing 'the vtbclient parser'

**`phase` records what you SAY you are doing and does not set the phase your
card is filed under.** That is derived from your own tool calls
(`../boardphase.py`); he sees both, side by side, on purpose. Say it anyway —
it is the only line that carries WHAT you are working on rather than which verb
you last used.

**A worker has a name.** It is minted beside the coded id when the worker
is spawned and it is what every line here identifies it by — his call: *"i think
itd be interesting to have them referred to by regular names"*. The id is still
the only key: the systemd unit, `~/.cache/board-work/<id>.log` and the inbox
directory are all named by it, so it is printed in parentheses after the name.
`inbox send --to` accepts either.

**`ask` refuses without `--if-unanswered`.** Every question on this board draws
that sentence, always; it is what makes a question safe to walk away from.

**If you are an agent, run `inbox take` between steps.** It is how a sentence he
typed into the board's agents section while you were already running reaches
you: your stdin is closed, so the only channel is a file you poll. It prints his
words and nothing else, they outrank the prompt you started with, and taking
them is what stops the watcher escalating them to another agent later. The
mechanism, the guarantees and what the box can and cannot promise are in
`boardagents.py`'s docstring.

Every one of those is a targeted line edit under an advisory lock, with a
digest re-check and an atomic replace (`boardparse.edit`) — so it is safe to run
while he has the board open, while the five-minute docs sync is running, and
while another agent is doing the same thing. Nothing it does not name comes out
different, byte for byte.

SELECTORS are forgiving on purpose, because the caller is usually a language
model holding a decision's title and not its slug: a number (`4`), the slug, or
any unambiguous part of the title. Ambiguity is an error, never a guess.

**`land` does not need an IN FLIGHT row.** A decision agent has one; a worker
dispatched out of the box never did, so for a day the fan-out's commits reached
LANDED never — `land` refused, and `note` was all a worker could reach. Every
agent that commits something records it here, with or without a row.

WHAT IT WILL NOT DO. It does not resolve a decision — `start` refuses an item he
has not answered (`--force` if you genuinely mean to, and say why on the board).
It does not delete anything: `land` moves a row to LANDED, `back` returns the
whole decision verbatim from the stash, and `stall` — the exit for a row no
stash on this host owns, which is most of what IN FLIGHT accumulates — moves the
row's three cells into WAITING ON YOU TO DO rather than dropping them. And it
writes no ages, elapsed times or counts anywhere in the file — a LANDED row's
`when` is the commit's own time, a fact about the past and not a clock running
against him; see `boardmove.py`.

`--board PATH` points it at a fixture instead of the real store; that is how
`tools/board-test.py` drives it.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boardagents as ba                                           # noqa: E402
import boardmove as bm                                             # noqa: E402
import boardparse as bp                                            # noqa: E402
import boardphase as bph                                           # noqa: E402
import boardwork as bw                                             # noqa: E402


def cmd_start(a):
    rec = bm.start(a.selector, where=a.where, notes=a.notes, pid=a.pid,
                   path=a.board, force=a.force)
    print("in flight: " + rec["row"].strip())
    print("stashed:   " + bm.stash_file(rec["key"]))
    return 0


def cmd_land(a):
    row = bm.land(a.selector, a.commit, what=a.what, date=a.date, when=a.when,
                  path=a.board)
    what = a.what or row.get("what") or a.commit
    bw.mark_reported(what=what)
    when = bm.commit_time(a.commit) if a.when is None else a.when
    print("landed: %s (%s%s)" % (what, a.commit, ", " + when if when else ""))
    if not row:
        # No IN FLIGHT row was moved — the commit was simply recorded. Say so,
        # rather than letting it read as though something moved sections.
        print("recorded in LANDED; nothing was moved out of IN FLIGHT")
    return 0


def cmd_back(a):
    rec = bm.give_back(a.selector, why=a.why, path=a.board)
    print("back in NEEDS YOU: " + rec["title"])
    return 0


def _note_text(argv):
    """The argv of `note`, as one MESSAGE PER ASK.

    Ordinary use is one quoted string and joins with a space as it always did.
    But `note 'COMPLETION: a' 'PARTIAL: b'` is two messages, and joining those
    with a space made one bullet claiming to be both — the bundling his
    separation rule exists to stop (`boardparse.check_one_ask`). Every argument
    after the first that STARTS with a tag is therefore its own line, which
    `boardmove.note` turns into its own bullet, with its own stamp, clearable on
    its own.
    """
    out = []
    for word in argv:
        if out and bp.is_tagged(word):
            out.append(word)
        elif out:
            out[-1] += " " + word
        else:
            out.append(word)
    return "\n".join(out)


def cmd_note(a):
    if bm.note(_note_text(a.text), path=a.board):
        # ...and, if a worker wrote it, that it reported AT ALL. `reap()` reads
        # exactly this: a worker whose process goes without one of `note`,
        # `land` or `ask` behind it is reported to him as having stopped without
        # finishing, rather than being silently indistinguishable from success.
        bw.mark_reported(what=_note_text(a.text))
        print("added to WAITING ON YOU TO DO")
        return 0
    print("nothing written", file=sys.stderr)
    return 1


def cmd_stall(a):
    row = bm.stall(a.selector, path=a.board)
    print("out of IN FLIGHT, into WAITING ON YOU TO DO: " + row["what"])
    return 0


def cmd_reconcile(a):
    moved = bm.reconcile(path=a.board)
    for rec in moved:
        print("returned to NEEDS YOU (its agent is gone): " + rec["title"])
    if not moved:
        print("nothing stranded")
    # ...and the rows reconcile structurally cannot reach. Reported, never
    # acted on: this host has no way to tell a row the OTHER machine is working
    # from one nothing is. Saying nothing is how the section silted up.
    rest = bm.unowned(path=a.board)
    if rest:
        print("%d row(s) no stash on this host owns - `boardctl.py stall "
              "<row>` moves one to WAITING ON YOU TO DO:" % len(rest))
        for r in rest:
            print("  " + r["what"])
    return 0


def cmd_list(a):
    st = bm.status(path=a.board)
    print("NEEDS YOU")
    for it in st["needs"]:
        print("  %-3s %-58s %s" % (it["num"] or "-", it["title"][:58],
                                   "answered" if it["answered"] else ""))
    print("IN FLIGHT")
    for r in st["flight"]:
        owned = st["stashed"].get(bm._norm(r["what"]))
        print("  %-62s %s%s" % (r["what"][:62], r["where"],
                                "  [returnable]" if owned else ""))
    return 0


def _who(ag):
    """How an agent is IDENTIFIED in this tool's output: by its first name, with
    the coded id after it because that is what its log and its unit are called.
    A row with neither — a task queued above the cap — has nobody on it yet and
    is not given a name it has not got."""
    name, aid = ag.get("name") or "", ag.get("id") or ""
    if name and aid:
        return "%s (%s)" % (name, aid)
    return name or aid


def _resolve_to(who):
    """`--to` takes an id OR a first name, because the name is what he reads on
    the card and on the orchestrator's note. Case-insensitive; an id wins, since
    that is the thing nothing else can collide with."""
    want = (who or "").strip().lower()
    if not want:
        return None
    rows = ba.agents()
    for ag in rows:
        if ag["id"].lower() == want:
            return ag["id"]
    for ag in rows:
        if (ag.get("name") or "").lower() == want:
            return ag["id"]
    return who


def cmd_agents(a):
    for g in bw.groups():
        print(g["label"].upper())
        for ag in g["rows"]:
            print("  %-20s %-46s %s" % (_who(ag), ag["title"][:46], ag["where"]))
            # The two statements, kept apart on the page exactly as the card
            # keeps them apart on screen. `says` is the agent; `actually` is its
            # transcript. Never merged, never one used for the other.
            if ag.get("says"):
                print("      says:   " + ag["says"][:70])
            print("      doing:  " + str(ag.get("actually") or "")[:70])
            if ag.get("unread"):
                print("      %d unread note(s) - `boardctl.py inbox take`"
                      % ag["unread"])
    q = ba.pending()
    if q:
        print("QUEUED FOR THE NEXT AGENT")
        for m in q:
            print("  " + m["text"][:100])
    return 0


def cmd_dispatch(a):
    rec = bw.dispatch(" ".join(a.task), where=a.where, context=a.context)
    if rec is None:
        print("boardctl: nothing to dispatch", file=sys.stderr)
        return 1
    if rec["state"] == "queued":
        print("queued (%d already running, the cap is %d) - a later tick starts it: %s"
              % (len(bw.live_workers()), bw.cap(), rec["task"][:70]))
        return 0
    if rec["state"] == "failed":
        print("boardctl: could not start a worker - " + rec.get("why", "?"),
              file=sys.stderr)
        return 1
    # STARTED, and that is all this can honestly say. The worker records its own
    # result on the board when it finishes; if it stops without one, the next
    # board-watch tick says so. See `boardwork.reap()`.
    # THE NAME IS WHAT THE NOTE SAYS. It is printed first and by itself because
    # the orchestrator reads this line and writes one identifier down from it;
    # the id follows because the log and the unit are named after it.
    print("started as %s - id %s, unit %s%s - nothing has landed yet: %s"
          % (rec.get("name") or rec["id"], rec["id"], bw.UNIT_PREFIX, rec["id"],
             rec["task"][:70]))
    return 0


def cmd_phase(a):
    """What the agent SAYS. It does not set the phase its card is filed under —
    that is read from the agent's own transcript and cannot be written from
    here. Say so on every call, so no agent is left believing it drove the UI."""
    try:
        rec = bph.claim(a.id, phase=a.phase, doing=a.doing)
    except ValueError as e:
        # Refused, not swallowed: the caller can fix it in one more call.
        print("boardctl: %s (got %r)" % (e, a.phase), file=sys.stderr)
        return 1
    if rec is None:
        print("boardctl: no agent id (set BOARD_AGENT_ID, or pass --id)",
              file=sys.stderr)
        return 1
    print("recorded what you say you are doing: " + (bph.says(rec) or "(nothing)"))
    print("the phase on your card is read from your tool calls, not from this")
    return 0


def cmd_ask(a):
    key = bm.ask(" ".join(a.question), context=a.context, options=a.option,
                 if_unanswered=a.if_unanswered, asked_by=a.asked_by, path=a.board)
    bw.seed_watch_state(key)
    bw.mark_reported(what="asked: " + " ".join(a.question))
    print("asked, in NEEDS YOU: " + " ".join(a.question)[:90])
    print("he answers it whenever he likes; nothing waits on it")
    return 0


def cmd_cap(a):
    if a.n is None:
        print(bw.cap())
        return 0
    print("at most %d workers at once" % bw.set_cap(a.n))
    return 0


def cmd_inbox(a):
    if a.what == "take":
        msgs = ba.take(a.id, include_queue=a.queue)
        # SEPARATE them, because two notes are two asks. `send()` collapses each
        # message to a single line, so N of them printed bare are N adjacent
        # lines of his prose with nothing between: an agent that polls after a
        # long step and finds two waiting reads one paragraph and answers the
        # first ask in it. Measured on 2026-07-29 — Purson (`w88cd31`) took two
        # in one call at 11:01 and Usiel (`w7a3ff2`) two at 10:20 — and it is
        # exactly the shape of *"all the queued messages after its initial
        # request were swallowed"*. One note still prints bare: the framing
        # exists to answer "how many", and with one there is no question.
        for i, m in enumerate(msgs, 1):
            if len(msgs) > 1:
                print("--- %d of %d, sent %s ---"
                      % (i, len(msgs), (m.get("at") or "")[11:16]))
            print(m["text"])
        if len(msgs) > 1:
            print("--- end of %d notes. EACH ONE is a separate ask; do them "
                  "all, and record each as it finishes ---" % len(msgs))
        if not msgs and not a.quiet:
            print("(nothing in your inbox)")
        return 0
    if a.what == "send":
        msg = ba.send(" ".join(a.text), to=_resolve_to(a.to))
        if msg is None:
            print("boardctl: nothing to send", file=sys.stderr)
            return 1
        print("%s: %s" % (msg["state"], msg["text"][:120]))
        return 0
    if a.what == "sweep":
        moved, dropped = ba.sweep()
        for m in moved:
            print("to the queue: " + m["text"][:100])
        for r in dropped:
            print("dropped a dead registration: " + str(r.get("title")))
        return 0
    for m in ba.pending():
        print("queued  " + m["text"][:100])
    for ag in ba.agents():
        for m in ba.for_agent(ag["id"]):
            print("unread  [%s] %s" % (_who(ag) or ag["title"][:30],
                                       m["text"][:100]))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="boardctl", description=__doc__.split("\n")[0])
    p.add_argument("--board", default=bp.BOARD_PATH)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="move an answered decision into IN FLIGHT")
    s.add_argument("selector")
    s.add_argument("--where", default="agent", help="the `where` column: the code it touches")
    s.add_argument("--notes", default=None,
                   help="override the note; the default reads his answer back to him")
    s.add_argument("--pid", type=int, default=None,
                   help="the process working it, so a stranded item can be reclaimed")
    s.add_argument("--force", action="store_true",
                   help="start an UNANSWERED decision (say why on the board)")
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("land", help="record a commit in LANDED (and move its "
                                    "IN FLIGHT row, if it has one)")
    s.add_argument("selector", nargs="?", default="",
                   help="an IN FLIGHT row to move; omit if you have none")
    s.add_argument("--commit", required=True)
    s.add_argument("--what", default=None,
                   help="one line; defaults to the row's own, and is REQUIRED "
                        "when there is no row")
    s.add_argument("--date", default=None, help="YYYY-MM-DD; defaults to today")
    s.add_argument("--when", default=None,
                   help="the time, 12-hour; defaults to the commit's own "
                        "committer date, read from git")
    s.set_defaults(fn=cmd_land)

    s = sub.add_parser("back", help="return a stranded IN FLIGHT item to NEEDS YOU")
    s.add_argument("selector")
    s.add_argument("--why", default=None,
                   help="a bullet for WAITING ON YOU TO DO; same tag rule as "
                        "`note`, and usually `FAILED:`")
    s.set_defaults(fn=cmd_back)

    s = sub.add_parser("note", help="add one bullet to WAITING ON YOU TO DO; it "
                                    "must start with %s, then a short "
                                    "description, then any background. ONE ASK "
                                    "PER BULLET - pass several tagged strings, "
                                    "or several lines, for several items"
                                    % "/".join(t + ":" for t in bp.TODO_TAGS))
    s.add_argument("text", nargs="+")
    s.set_defaults(fn=cmd_note)

    s = sub.add_parser("stall", help="an IN FLIGHT row nothing owns -> one "
                                     "bullet in WAITING ON YOU TO DO")
    s.add_argument("selector")
    s.set_defaults(fn=cmd_stall)

    s = sub.add_parser("reconcile", help="return every item whose agent has died")
    s.set_defaults(fn=cmd_reconcile)

    s = sub.add_parser("list", help="what is where")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("agents", help="who is running right now, by phase")
    s.set_defaults(fn=cmd_agents)

    s = sub.add_parser("dispatch", help="hand one piece of work to a worker agent")
    s.add_argument("task", nargs="+")
    s.add_argument("--where", default="", help="the files it will touch")
    s.add_argument("--context", default="",
                   help="what you know that the worker does not")
    s.set_defaults(fn=cmd_dispatch)

    s = sub.add_parser("phase", help="say what YOU are doing (the card also "
                                     "shows what you are observed doing)")
    # ANY single word, not a fixed list — his call: *"allow agents more freedom
    # to indicate what they are doing, but it should still only be a single
    # word"*. `bph.clean_phase_word` is what "a word" means, and the classic
    # five are still the ones a transcript can produce on its own.
    s.add_argument("phase", nargs="?", default="",
                   help="one word for what you are doing (%s, or your own)"
                        % ", ".join(bph.CLAIMABLE))
    s.add_argument("--doing", default="", help="one short line, present tense")
    s.add_argument("--id", default=None, help="default: $BOARD_AGENT_ID")
    s.set_defaults(fn=cmd_phase)

    s = sub.add_parser("ask", help="park a question for him in NEEDS YOU")
    s.add_argument("question", nargs="+")
    s.add_argument("--context", action="append", default=[],
                   help="a paragraph of what raises it; repeatable")
    s.add_argument("--option", action="append", default=[],
                   help="an alternative he can tick; repeatable")
    s.add_argument("--if-unanswered", dest="if_unanswered", default="",
                   help="REQUIRED: what happens if he never answers")
    s.add_argument("--asked-by", dest="asked_by", default=None,
                   help="what you were working on when it came up")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("cap", help="how many workers may run at once")
    s.add_argument("n", nargs="?", type=int, default=None)
    s.set_defaults(fn=cmd_cap)

    s = sub.add_parser("inbox", help="his mid-flight notes to a running agent")
    s.add_argument("what", nargs="?", default="list",
                   choices=["list", "take", "send", "sweep"])
    s.add_argument("text", nargs="*", help="send: the note")
    s.add_argument("--id", default=None,
                   help="take: whose inbox (default: $BOARD_AGENT_ID, else this session)")
    s.add_argument("--to", default=None,
                   help="send: an agent id or its first name; omit to queue it")
    s.add_argument("--queue", action="store_true",
                   help="take: drain the queue too (board-watch only)")
    s.add_argument("--quiet", action="store_true", help="take: print nothing if empty")
    s.set_defaults(fn=cmd_inbox)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except bm.BoardError as e:
        print("boardctl: " + str(e), file=sys.stderr)
        return 1
    except OSError as e:
        print("boardctl: " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
