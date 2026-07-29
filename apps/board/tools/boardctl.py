#!/usr/bin/env python3
"""boardctl — move an item on `docs/board.md` without hand-editing it.

The board is a markdown file (`apps/board/AGENTS.md`), and until this existed
the only ways to move an item on it were the GUI, which deliberately never moves
anything, and a text editor, which is how half-written rows and reflowed tables
happen. This is the third way, and it is the one an agent should use:

    boardctl.py start 4 --where 'apps/player/**'   # NEEDS YOU -> IN FLIGHT
    boardctl.py land 'cover art' --commit a3c2aac --what 'player: dim the art'
    boardctl.py back 'cover art' --why 'blocked on the FOCUS signal'
    boardctl.py note '**Relaunch `player`** - live source, no hot reload.'
    boardctl.py list

    boardctl.py agents                             # who is running right now
    boardctl.py inbox take                         # HIS notes to you, mid-flight
    boardctl.py inbox send 'also fix the tooltip' --to <agent id>

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

WHAT IT WILL NOT DO. It does not resolve a decision — `start` refuses an item he
has not answered (`--force` if you genuinely mean to, and say why on the board).
It does not delete anything: `land` moves a row to LANDED, `back` returns the
whole decision verbatim from the stash. And it writes no times, ages or counts
anywhere in the file; see `boardmove.py`.

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


def cmd_start(a):
    rec = bm.start(a.selector, where=a.where, notes=a.notes, pid=a.pid,
                   path=a.board, force=a.force)
    print("in flight: " + rec["row"].strip())
    print("stashed:   " + bm.stash_file(rec["key"]))
    return 0


def cmd_land(a):
    row = bm.land(a.selector, a.commit, what=a.what, date=a.date, path=a.board)
    print("landed: %s (%s)" % (a.what or row["what"], a.commit))
    return 0


def cmd_back(a):
    rec = bm.give_back(a.selector, why=a.why, path=a.board)
    print("back in NEEDS YOU: " + rec["title"])
    return 0


def cmd_note(a):
    if bm.note(" ".join(a.text), path=a.board):
        print("added to WAITING ON YOU TO DO")
        return 0
    print("nothing written", file=sys.stderr)
    return 1


def cmd_reconcile(a):
    moved = bm.reconcile(path=a.board)
    for rec in moved:
        print("returned to NEEDS YOU (its agent is gone): " + rec["title"])
    if not moved:
        print("nothing stranded")
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


def cmd_agents(a):
    for ag in ba.agents():
        print("  %-10s %-52s %s" % (ag["state"], ag["title"][:52], ag["where"]))
        if ag["unread"]:
            print("             %d unread note(s) - `boardctl.py inbox take`"
                  % ag["unread"])
    q = ba.pending()
    if q:
        print("QUEUED FOR THE NEXT AGENT")
        for m in q:
            print("  " + m["text"][:100])
    return 0


def cmd_inbox(a):
    if a.what == "take":
        msgs = ba.take(a.id, include_queue=a.queue)
        for m in msgs:
            print(m["text"])
        if not msgs and not a.quiet:
            print("(nothing in your inbox)")
        return 0
    if a.what == "send":
        msg = ba.send(" ".join(a.text), to=a.to)
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
            print("unread  [%s] %s" % (ag["title"][:30], m["text"][:100]))
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

    s = sub.add_parser("land", help="move an IN FLIGHT row into LANDED with its commit")
    s.add_argument("selector")
    s.add_argument("--commit", required=True)
    s.add_argument("--what", default=None, help="one line; defaults to the row's own")
    s.add_argument("--date", default=None, help="YYYY-MM-DD; defaults to today")
    s.set_defaults(fn=cmd_land)

    s = sub.add_parser("back", help="return a stranded IN FLIGHT item to NEEDS YOU")
    s.add_argument("selector")
    s.add_argument("--why", default=None, help="a bullet for WAITING ON YOU TO DO")
    s.set_defaults(fn=cmd_back)

    s = sub.add_parser("note", help="add one bullet to WAITING ON YOU TO DO")
    s.add_argument("text", nargs="+")
    s.set_defaults(fn=cmd_note)

    s = sub.add_parser("reconcile", help="return every item whose agent has died")
    s.set_defaults(fn=cmd_reconcile)

    s = sub.add_parser("list", help="what is where")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("agents", help="who is running right now")
    s.set_defaults(fn=cmd_agents)

    s = sub.add_parser("inbox", help="his mid-flight notes to a running agent")
    s.add_argument("what", nargs="?", default="list",
                   choices=["list", "take", "send", "sweep"])
    s.add_argument("text", nargs="*", help="send: the note")
    s.add_argument("--id", default=None,
                   help="take: whose inbox (default: $BOARD_AGENT_ID, else this session)")
    s.add_argument("--to", default=None, help="send: an agent id; omit to queue it")
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
