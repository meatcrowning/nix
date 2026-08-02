#!/usr/bin/env python3
"""Offscreen tests for the rejected-download re-source in soulseek-missing.py.

Every test here is synthetic -- no network, no live slskd, no player. It
builds fake /transfers/downloads responses and fake state files in the exact
shape slskd returns (username -> directories -> files, each file carrying its
own username/filename/id/state) and drives the pure helpers in
soulseek-missing.py: iter_transfers, transfer_failed, rescue_rejected,
pick_candidate and the rescued-id persistence.

Runs under a bare python3 on either host; imports the target module via
importlib because its filename (soulseek-missing.py) is not a valid identifier.

    python3 apps/player/tools/soulseek-rescue-test.py
"""

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "soulseek_missing", HERE / "soulseek-missing.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

TRACK = {
    "artists": "Rick Astley",
    "title": "Never Gonna Give You Up",
    "album": "Whenever You Need Somebody",
    "year": "1987",
    "duration_ms": "213000",
    "isrc": "ISRCX",
    "spotify_id": "SPOTID00001",
}
REJECTED_FILENAME = "Music\\Rick Astley\\01 Never Gonna Give You Up.mp3"
GOOD_FILENAME = "flac\\Rick Astley\\Never Gonna Give You Up (7\" mix).flac"


def dl_response(*file_objs):
    """Build a /transfers/downloads-shaped nested response from file objects."""
    files = [dict(f) for f in file_objs]
    by_user = {}
    for f in files:
        u = f.setdefault("username", "peer")
        f.setdefault("state", "InProgress")
        by_user.setdefault(u, []).append(f)
    return [{"username": u,
             "directories": [{"directory": "/", "fileCount": len(fl),
                              "files": fl}]}
            for u, fl in by_user.items()]


def failed_transfer(user, filename, reason="Completed, Rejected", tid="tid-1"):
    return {"id": tid, "username": user, "filename": filename, "state": reason,
            "bytesTransferred": 0, "exception": "Transfer rejected: Banned"}


def queued(sid, user, filename):
    return {"spotify_id": sid, "isrc": "", "status": "queued", "user": user,
            "filename": filename, "when": "2026-08-01 00:00:00"}


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAIL: {name}")
    print(f"  ok: {name}")


def test_iter_transfers():
    print("iter_transfers")
    dl = dl_response(
        failed_transfer("alice", "a\\one.mp3"),
        {"username": "alice", "filename": "a\\two.mp3", "state": "InProgress"},
        {"username": "bob", "filename": "b\\one.flac",
         "state": "Completed, Succeeded"},
    )
    flat = list(S.iter_transfers(dl))
    check("flattens the nested response to every file", len(flat) == 3)
    check("each file keeps its own username",
          {f["username"] for f in flat} == {"alice", "bob"})


def test_transfer_failed():
    print("transfer_failed")
    for state in ("Completed, Rejected", "Completed, Cancelled",
                  "Completed, TimedOut", "Completed, Errored",
                  "Completed, Aborted"):
        check(f"flags {state!r} as failed", S.transfer_failed({"state": state}))
    for state in ("Completed, Succeeded", "Completed", "InProgress",
                  "Queued, Remotely", "Queued, Locally", "Requested"):
        check(f"does not flag {state!r}", not S.transfer_failed({"state": state}))
    check("missing state is not failed", not S.transfer_failed({}))


def test_alive_transfers_excludes_failed():
    print("alive_transfers: failed terminals do not guard re-queueing")
    dl = dl_response(
        failed_transfer("rejector", REJECTED_FILENAME, reason="Completed, Rejected",
                        tid="t1"),
        {"username": "ongoing", "filename": "o\\one.mp3", "state": "InProgress"},
        {"username": "done", "filename": "d\\two.mp3",
         "state": "Completed, Succeeded"},
        failed_transfer("erro", REJECTED_FILENAME, reason="Completed, Errored",
                        tid="t2"),
    )
    alive = S.alive_transfers(dl)
    check("the rejected transfer is excluded", ("rejector", REJECTED_FILENAME)
          not in alive)
    check("the errored transfer is excluded", ("erro", REJECTED_FILENAME)
          not in alive)
    check("in-progress transfer is included", ("ongoing", "o\\one.mp3") in alive)
    check("succeeded transfer is included", ("done", "d\\two.mp3") in alive)


def test_rescue_rejected_resources_and_blocks():
    print("rescue_rejected: re-source + block")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "rejector", REJECTED_FILENAME)}
    rescued = set()
    dl = dl_response(failed_transfer("rejector", REJECTED_FILENAME, tid="t1"))
    blocked, n = S.rescue_rejected(rows, state, rescued, dl, dry_run=False)
    check("blocks the rejecting peer", blocked == {"rejector"})
    check("re-sources the matching track", n == 1)
    check("drops the queued marker (track becomes wanted)",
          "SPOTID00001" not in state)
    check("remembers the rejected transfer id", "t1" in rescued)


def test_rescue_rejected_errored_resources():
    print("rescue_rejected: errored download is re-sourced and blocked")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "rejector", REJECTED_FILENAME)}
    rescued = set()
    dl = dl_response(failed_transfer("rejector", REJECTED_FILENAME,
                                     reason="Completed, Errored", tid="t1"))
    blocked, n = S.rescue_rejected(rows, state, rescued, dl, dry_run=False)
    check("blocks the peer that errored", blocked == {"rejector"})
    check("re-sources the errored track", n == 1)
    check("drops the queued marker", "SPOTID00001" not in state)
    check("remembers the errored transfer id", "t1" in rescued)


def test_rescue_rejected_no_state_does_not_burn_id():
    print("rescue_rejected: a transfer with no matching queued state is not "
          "recorded as handled")
    # A failed transfer can map to a work-list track that has no "queued"
    # state record (e.g. it is already "nofind"/error, or the entry was
    # dropped). Recording its id in rescued_ids then would burn it forever
    # with nothing re-sourced -- and once the track is queued again later, the
    # same lingering rejection could never be acted on. The id must only be
    # remembered (and the peer only blocked) when a queue actually happened.
    rows = [dict(TRACK)]
    state = {"SPOTID00001": {"spotify_id": "SPOTID00001", "isrc": "",
                             "status": "nofind", "user": "", "filename": "",
                             "when": "2026-08-01 00:00:00"}}
    rescued = set()
    dl = dl_response(failed_transfer("rejector", REJECTED_FILENAME, tid="t1"))
    blocked, n = S.rescue_rejected(rows, state, rescued, dl, dry_run=False)
    check("no re-source (track was not queued)", n == 0)
    check("no peer blocked for an unacted rejection", blocked == set())
    check("transfer id NOT burned", rescued == set())


def test_rescue_rejected_no_state_then_queued_still_handled():
    print("rescue_rejected: a no-state rejection can be re-sourced once the "
          "track is later queued")
    rows = [dict(TRACK)]
    rescued = set()
    dl = dl_response(failed_transfer("rejector", REJECTED_FILENAME, tid="t1"))
    # first pass: the track has no state yet
    state1 = {}
    blocked, n = S.rescue_rejected(rows, state1, rescued, dl, dry_run=False)
    check("nothing burned when nothing queued", rescued == set() and n == 0)
    # later the same track is queued (from a different peer), and the OLD
    # rejection is still lingering in slskd's list
    state2 = {"SPOTID00001": queued("SPOTID00001", "goodpeer", GOOD_FILENAME)}
    blocked, n = S.rescue_rejected(rows, state2, rescued, dl, dry_run=False)
    check("the lingering rejection is now re-sourced", n == 1)
    check("track re-queued becomes wanted", "SPOTID00001" not in state2)
    check("id remembered only after acting", "t1" in rescued)


def test_rescue_rejected_divergent_source_still_resources():
    print("rescue_rejected: re-sources even when the recorded source diverged")
    # The recorded source for a track is often a *different* peer/file than a
    # stale rejected transfer that maps to the same track. Matching by
    # artist/title (not by the recorded source) must still re-source it.
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "goodpeer", GOOD_FILENAME)}
    rescued = set()
    dl = dl_response(failed_transfer("rejector", REJECTED_FILENAME, tid="t1"))
    blocked, n = S.rescue_rejected(rows, state, rescued, dl, dry_run=False)
    check("re-sources the divergent recorded source", n == 1)
    check("track becomes wanted again", "SPOTID00001" not in state)
    check("the rejecting peer is blocked for the re-source", blocked == {"rejector"})


def test_rescue_rejected_unrelated_unaffected():
    print("rescue_rejected: a rejection for an unknown song touches nothing")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "goodpeer", GOOD_FILENAME)}
    rescued = set()
    dl = dl_response(failed_transfer("stranger",
                                     "z\\Totally Unrelated - Some Song.mp3",
                                     tid="t9"))
    blocked, n = S.rescue_rejected(rows, state, rescued, dl, dry_run=False)
    check("blocks nobody", blocked == set() and n == 0)
    check("track stays queued", state["SPOTID00001"]["status"] == "queued")
    check("nothing recorded as rescued", rescued == set())


def test_rescue_rejected_dry_run_no_mutation():
    print("rescue_rejected: --dry-run does not mutate state")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "rejector", REJECTED_FILENAME)}
    rescued = set()
    dl = dl_response(failed_transfer("rejector", REJECTED_FILENAME, tid="t1"))
    blocked, n = S.rescue_rejected(rows, state, rescued, dl, dry_run=True)
    check("reports the re-source it would do", n == 1)
    check("queued marker is preserved in a preview",
          "SPOTID00001" in state)
    check("peer still blocked for a preview run", blocked == {"rejector"})


def test_rescue_rejected_loop_free_via_rescued_set():
    print("rescue_rejected: a lingering rejected transfer does not loop")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "rejector", REJECTED_FILENAME)}
    rescued = set()
    dl = dl_response(failed_transfer("rejector", REJECTED_FILENAME, tid="t1"))
    blocked, n = S.rescue_rejected(rows, state, rescued, dl, dry_run=False)
    check("first run re-sources", n == 1 and "SPOTID00001" not in state)
    # simulate the re-source: track now recorded under a different peer
    state["SPOTID00001"] = queued("SPOTID00001", "goodpeer", GOOD_FILENAME)
    # the OLD rejected transfer still lingers in slskd's list, same id
    blocked2, n2 = S.rescue_rejected(rows, state, rescued, dl, dry_run=False)
    check("no second re-source for an already-handled rejection", n2 == 0)
    check("track stays under the good peer",
          state["SPOTID00001"]["user"] == "goodpeer")


def test_rescue_rejected_new_peer_rejection_still_handled():
    print("rescue_rejected: a *new* rejection of the re-sourced peer is handled")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "goodpeer", GOOD_FILENAME)}
    rescued = {"t1"}  # old rejection already handled
    dl2 = dl_response(failed_transfer("goodpeer", GOOD_FILENAME, tid="t2"))
    blocked, n = S.rescue_rejected(rows, state, rescued, dl2, dry_run=False)
    check("a fresh rejection is re-sourced again", n == 1)
    check("the new rejector is blocked", blocked == {"goodpeer"})
    check("the new transfer id is remembered", "t2" in rescued)


def test_pick_candidate_skips_blocked_peer():
    print("pick_candidate: skips peers that refused a download")
    resp = {
        "username": "rejector",
        "files": [{"filename": "m\\Rick Astley\\01 Never Gonna Give You Up.mp3",
                   "length": 213, "bitRate": 320}],
    }
    resp_good = {
        "username": "goodpeer",
        "files": [{"filename": "flac\\Rick Astley\\Never Gonna Give You Up.flac",
                   "length": 215, "bitRate": 0}],
    }
    best = S.pick_candidate([resp_good, resp], TRACK["artists"],
                            TRACK["title"], 213000)
    check("rejector is the best when nothing is blocked", best[0] == "rejector")
    best_blocked = S.pick_candidate([resp_good, resp], TRACK["artists"],
                                    TRACK["title"], 213000,
                                    skip_users={"rejector"})
    check("blocked peer is never picked", best_blocked is not None
          and best_blocked[0] == "goodpeer")


def test_rescued_persistence_roundtrip(tmp_path):
    print("load_rescued / save_rescued roundtrip")
    p = tmp_path / "soulseek-rescued.json"
    ids = {"a", "b", "c"}
    S.save_rescued(str(p), ids)
    check("survives a roundtrip", S.load_rescued(str(p)) == ids)
    check("missing/stale file loads empty",
          S.load_rescued(str(tmp_path / "nope.json")) == set())


def clear_state():
    saved = {}
    def fake_http(method, url, api_key, body=None):
        saved["calls"] = saved.get("calls", []) + [(method, url)]
        return None
    return fake_http, saved


def test_clear_handled_failures_dry_run_counts_no_mutation():
    print("clear_handled_failures: --dry-run counts every failed transfer, "
          "mutates nothing")
    dl = dl_response(
        failed_transfer("rejector", REJECTED_FILENAME, reason="Completed, Rejected",
                        tid="clear-1"),
        failed_transfer("erro", REJECTED_FILENAME, reason="Completed, Errored",
                        tid="clear-2"),
        {"username": "ongoing", "filename": "o\\\\one.mp3", "state": "InProgress"},
        {"username": "done", "filename": "d\\\\two.mp3",
         "state": "Completed, Succeeded"},
    )
    fake_http, saved = clear_state()
    orig_http = S.http
    S.http = fake_http
    try:
        n = S.clear_handled_failures("http://x", "k", dl, dry_run=True)
    finally:
        S.http = orig_http
    check("counts every failed-terminal transfer (2 here)", n == 2)
    check("dry-run made no DELETE calls", saved.get("calls", []) == [])


def test_clear_handled_failures_deletes_and_counts():
    print("clear_handled_failures: every failed transfer is DELETE-cleanable")
    dl = dl_response(
        failed_transfer("rejector", REJECTED_FILENAME, reason="Completed, Rejected",
                        tid="clear-1"),
        failed_transfer("erro", "e\\\\two.mp3", reason="Completed, Errored",
                        tid="clear-2"),
        failed_transfer("unhandled", "u\\\\three.mp3",
                        reason="Completed, TimedOut", tid="clear-3"),
        {"username": "done", "filename": "d\\\\four.mp3",
         "state": "Completed, Succeeded"},
    )
    fake_http, saved = clear_state()
    orig_http = S.http
    S.http = fake_http
    try:
        n = S.clear_handled_failures("http://x", "k", dl, dry_run=False)
    finally:
        S.http = orig_http
    check("clears all three failed transfers, not only a 'rescued' subset",
          n == 3)
    urls = [u for m, u in saved["calls"] if m == "DELETE"]
    check("DELETE for each failed transfer", len(urls) == 3)
    check("the failed terminal is deleted too (it can never produce a file)",
          any("clear-3" in u for u in urls))
    check("a succeeded transfer is NOT deleted",
          all("d\\\\four.mp3" not in u for u in urls))
    check("DELETE carries ?remove=true (else slskd only cancels, the row stays)",
          all(u.endswith("?remove=true") for u in urls))


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tests = [(k, v) for k, v in sorted(globals().items())
                 if k.startswith("test_")]
        for k, t in tests:
            if "tmp_path" in t.__code__.co_varnames:
                t(tmp_path=Path(td))
            else:
                t()
            print()
        print(f"PASS: {len(tests)} test functions.")


if __name__ == "__main__":
    main()
