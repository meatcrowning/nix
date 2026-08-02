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
from datetime import datetime, timezone
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


def test_transfer_failed_zero_byte_succeeded():
    print("transfer_failed: completed-but-zero-bytes")
    check("flags succeeded-with-0-bytes-of-a-real-file as failed",
          S.transfer_failed({"state": "Completed, Succeeded",
                             "size": 5_000_000, "bytesTransferred": 0}))
    check("a real succeeded transfer (bytes == size) is not failed",
          not S.transfer_failed({"state": "Completed, Succeeded",
                                 "size": 5_000_000,
                                 "bytesTransferred": 5_000_000}))
    check("a partial succeeded transfer is not failed",
          not S.transfer_failed({"state": "Completed, Succeeded",
                                 "size": 5_000_000,
                                 "bytesTransferred": 4_000_000}))
    check("a genuinely zero-size succeeded transfer is not flagged here",
          not S.transfer_failed({"state": "Completed, Succeeded",
                                 "size": 0, "bytesTransferred": 0}))


def test_transfer_in_pipe_and_count():
    print("transfer_in_pipe / count_in_pipe")
    live = ("Queued, Remotely", "Queued, Locally", "Requested",
            "Initializing", "InProgress")
    for st in live:
        check(f"{st!r} counts as live", S.transfer_in_pipe({"state": st}))
    for st in ("Completed, Succeeded", "Completed, Rejected",
               "Completed, Errored"):
        check(f"{st!r} does not count as live",
              not S.transfer_in_pipe({"state": st}))
    check("zero-byte succeeded is not live",
          not S.transfer_in_pipe({"state": "Completed, Succeeded",
                                  "size": 100, "bytesTransferred": 0}))
    dl = dl_response(
        {"username": "a", "filename": "a\\1.mp3", "state": "InProgress"},
        {"username": "a", "filename": "a\\2.mp3", "state": "Queued, Remotely"},
        {"username": "b", "filename": "b\\1.mp3", "state": "Completed, Succeeded",
         "size": 10, "bytesTransferred": 10},
        failed_transfer("c", "c\\1.mp3"),
    )
    check("count_in_pipe counts only the two live transfers",
          S.count_in_pipe(dl) == 2)
    check("count_in_pipe of an empty list is 0", S.count_in_pipe([]) == 0)
    check("count_in_pipe of None is 0", S.count_in_pipe(None) == 0)


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


def test_pick_candidate_spreads_across_peers():
    print("pick_candidate: de-prioritizes a peer already loaded this run")
    # Two peers offer an equally good file; `avoided` is already carrying
    # MAX_ENQUEUES_PER_PEER files this run. The fresh peer must win so the
    # batch fans out instead of serializing behind one peer's upload slot.
    art, title = TRACK["artists"], TRACK["title"]
    resp_avoided = {"username": "overloaded",
                    "files": [{"filename": f"m\\\\{art}\\\\01 {title}.mp3",
                               "length": 213, "bitRate": 320}]}
    resp_fresh = {"username": "freshpeer",
                  "files": [{"filename": f"f\\\\{art}\\\\01 {title}.mp3",
                             "length": 213, "bitRate": 320}]}
    best = S.pick_candidate([resp_avoided, resp_fresh], art, title, 213000,
                            avoid_users={"overloaded"})
    check("fresh peer wins over a loaded one at equal quality",
          best is not None and best[0] == "freshpeer")
    check("with nothing avoided, the first-equal peer still wins",
          S.pick_candidate([resp_avoided, resp_fresh], art, title, 213000,
                           avoid_users=set())[0] == "overloaded")


def test_pick_candidate_avoid_is_bias_not_refusal():
    print("pick_candidate: an avoided peer is still used when it is the only "
          "source")
    art, title = TRACK["artists"], TRACK["title"]
    only = {"username": "solo",
            "files": [{"filename": f"m\\\\{art}\\\\01 {title}.wv",
                       "length": 213, "bitRate": 300}]}
    best = S.pick_candidate([only], art, title, 213000,
                            avoid_users={"solo"})
    check("the only source is picked even when it is avoided", best is not None
          and best[0] == "solo")


def test_pick_candidate_prefers_free_upload_slot():
    print("pick_candidate: a peer with a free upload slot wins at equal "
          "quality")
    art, title = TRACK["artists"], TRACK["title"]
    busy = {"username": "busy",
            "files": [{"filename": f"m\\\\{art}\\\\01 {title}.mp3",
                       "length": 213, "bitRate": 320}]}
    free = {"username": "freeslot", "hasFreeUploadSlot": True,
            "files": [{"filename": f"f\\\\{art}\\\\02 {title}.mp3",
                       "length": 213, "bitRate": 320}]}
    best = S.pick_candidate([busy, free], art, title, 213000)
    check("free-slot peer wins on the tiebreak", best is not None
          and best[0] == "freeslot")


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


def test_reconcile_orphaned_queued():
    print("reconcile_orphaned_queued: orphaned 'queued' markers")
    art, title = TRACK["artists"], TRACK["title"]
    sid = TRACK["spotify_id"]

    def rec(sid_, user, fn, status="queued"):
        return {"spotify_id": sid_, "isrc": "", "status": status,
                "user": user, "filename": fn, "when": "2026-08-01 00:00:00"}

    state = {
        sid: rec(sid, "ghost", "ghost\\\\01 %s.mp3" % title),      # orphan
        "SPOTID-LIVE": rec("SPOTID-LIVE", "livepeer", "live\\\\tune.flac"),
        "SPOTID-DL": rec("SPOTID-DL", "dlpeer", "dl\\\\07 DL only.mp3"),
        "SPOTID-LANDED": rec("SPOTID-LANDED", "landpeer",
                             "land\\\\Some Other Song.mp3"),
        "SPOTID-GONE": rec("SPOTID-GONE", "gone", "gone\\\\old.mp3"),
    }
    # work list rows: the orphan, the DL one, and the landed one
    rows = [
        dict(TRACK),                                        # sid (orphan)
        dict(TRACK, spotify_id="SPOTID-DL", title=title),
        dict(TRACK, spotify_id="SPOTID-LANDED", title="Some Other Song"),
    ]
    # a transfer is still working on SPOTID-LIVE only
    alive = {("livepeer", "live\\\\tune.flac")}
    # library holds "Some Other Song" but not the orphan track
    present = set(S.trackmatch.keys(art, "Some Other Song"))
    # a completed file for SPOTID-DL awaits import in the downloads dir
    downloaded = {S.trackmatch.fold("07 DL only.mp3")}

    # dry-run: counts the orphan, mutates nothing
    state_before = {k: dict(v) for k, v in state.items()}
    n = S.reconcile_orphaned_queued(state_before, alive, present, rows,
                                    downloaded, dry_run=True)
    check("dry-run counts the orphan and leaves state alone",
          n == 1 and sid in state_before)

    n = S.reconcile_orphaned_queued(state, alive, present, rows,
                                    downloaded, dry_run=False)
    check("real run re-queues exactly the orphan", n == 1)
    check("orphaned marker dropped", sid not in state)
    check("a live transfer keeps its queued marker",
          state["SPOTID-LIVE"]["status"] == "queued")
    check("a completed file awaiting import is not re-downloaded",
          state["SPOTID-DL"]["status"] == "queued")
    check("a track that landed is re-marked 'have'",
          state["SPOTID-LANDED"]["status"] == "have")
    check("an entry with no work-list row is left alone",
          "SPOTID-GONE" in state and state["SPOTID-GONE"]["status"] == "queued")


def test_stalled_transfer():
    print("stalled_transfer: queued-behind-a-congested-peer detection")
    now = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    huge = {"state": "Queued, Remotely", "placeInQueue": 45603}
    check("a huge queue position is stalled",
          S.stalled_transfer(huge, now, 1000, 24))
    small = {"state": "Queued, Remotely", "placeInQueue": 5,
             "enqueuedAt": "2026-08-01T00:01:00.000+00:00"}
    check("a short queue just queued is not stalled",
          not S.stalled_transfer(small, now, 1000, 24))
    old = {"state": "Queued, Remotely", "placeInQueue": 0,
           "enqueuedAt": "2026-07-30T00:00:00.000+00:00"}
    check("a place-0 transfer stuck past the time bar is stalled",
          S.stalled_transfer(old, now, 1000, 24))
    fresh = {"state": "Queued, Remotely", "placeInQueue": 0,
             "enqueuedAt": "2026-07-31T23:00:00.000+00:00"}
    check("a place-0 transfer queued inside the time bar is not stalled",
          not S.stalled_transfer(fresh, now, 1000, 24))
    naive_old = {"state": "Queued, Remotely", "placeInQueue": 0,
                 "enqueuedAt": "2026-07-30T00:00:00.000000"}  # no tz offset
    check("a naive (UTC) timestamp past the bar is still stalled",
          S.stalled_transfer(naive_old, now, 1000, 24))
    check("an in-progress transfer is never stalled",
          not S.stalled_transfer(
              {"state": "InProgress", "placeInQueue": 40000, "filename": "x"}, now, 1000, 24))
    check("a succeeded transfer is never stalled",
          not S.stalled_transfer(
              {"state": "Completed, Succeeded", "placeInQueue": 40000, "filename": "x"}, now, 1000, 24))
    check("a failed terminal is never stalled",
          not S.stalled_transfer(
              {"state": "Completed, Rejected", "placeInQueue": 40000, "filename": "x"}, now, 1000, 24))


def test_rescue_stalled_cancels_and_resources():
    print("rescue_stalled: re-sources a transfer stuck behind a congested peer")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "congested", REJECTED_FILENAME)}
    rescued = set()
    avoid = {}
    now = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    dl = dl_response({"username": "congested", "filename": REJECTED_FILENAME,
                      "state": "Queued, Remotely", "placeInQueue": 45603,
                      "id": "stall-1"})
    fake_http, saved = clear_state()
    orig = S.http
    S.http = fake_http
    try:
        blocked, n, rs_keys = S.rescue_stalled(rows, state, rescued, avoid, dl, now,
                                      "http://x", "k", dry_run=False,
                                      place_limit=1000, stall_hours=24)
    finally:
        S.http = orig
    check("blocks the congested peer", blocked == {"congested"})
    check("re-sources the track", n == 1)
    check("queued marker dropped -> track wanted", "SPOTID00001" not in state)
    check("congested peer remembered per-track",
          avoid.get("SPOTID00001") == {"congested"})
    check("transfer id remembered", "stall-1" in rescued)
    check("re-sourced track key returned",
          rs_keys == {"SPOTID00001"})
    deletes = [u for m, u in saved["calls"] if m == "DELETE"]
    check("cancels the frozen transfer with ?remove=true",
          len(deletes) == 1 and deletes[0].endswith("?remove=true"))


def test_rescue_stalled_dry_run_no_mutation():
    print("rescue_stalled: --dry-run mutates nothing")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "congested", REJECTED_FILENAME)}
    rescued = set()
    avoid = {}
    now = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    dl = dl_response({"username": "congested", "filename": REJECTED_FILENAME,
                      "state": "Queued, Remotely", "placeInQueue": 45603,
                      "id": "stall-d1"})
    fake_http, saved = clear_state()
    orig = S.http
    S.http = fake_http
    try:
        blocked, n, _rs = S.rescue_stalled(rows, state, rescued, avoid, dl, now,
                                      "http://x", "k", dry_run=True,
                                      place_limit=1000, stall_hours=24)
    finally:
        S.http = orig
    check("reports the re-source it would do", n == 1)
    check("queued marker preserved in a preview", "SPOTID00001" in state)
    check("no avoid recorded in a preview", avoid == {})
    check("no DELETE in a preview", saved.get("calls", []) == [])
    check("peer still blocked for the preview re-search", blocked == {"congested"})


def test_rescue_stalled_dedup_no_loop():
    print("rescue_stalled: an already-handled stall is not re-sourced")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "congested", REJECTED_FILENAME)}
    rescued = {"stall-1"}  # already acted on
    avoid = {}
    now = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    dl = dl_response({"username": "congested", "filename": REJECTED_FILENAME,
                      "state": "Queued, Remotely", "placeInQueue": 45603,
                      "id": "stall-1"})
    blocked, n, _rs = S.rescue_stalled(rows, state, rescued, avoid, dl, now,
                                  "http://x", "k", dry_run=False,
                                  place_limit=1000, stall_hours=24)
    check("no re-source for an already-handled transfer", n == 0 and blocked == set())
    check("track untouched", state["SPOTID00001"]["status"] == "queued")
    check("no peer added to avoid", avoid == {})


def test_rescue_stalled_unrelated_unaffected():
    print("rescue_stalled: a stalled transfer for an unknown song touches nothing")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "goodpeer", GOOD_FILENAME)}
    rescued = set()
    avoid = {}
    now = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    dl = dl_response({"username": "stranger", "filename": "z\\\\Totally Other - Song.mp3",
                      "state": "Queued, Remotely", "placeInQueue": 45603,
                      "id": "stall-99"})
    blocked, n, _rs = S.rescue_stalled(rows, state, rescued, avoid, dl, now,
                                  "http://x", "k", dry_run=False,
                                  place_limit=1000, stall_hours=24)
    check("blocks nobody", blocked == set() and n == 0)
    check("track stays queued", state["SPOTID00001"]["status"] == "queued")
    check("nothing recorded", avoid == {} and rescued == set())


def test_stall_avoid_persistence_roundtrip(tmp_path):
    print("load_stall_avoid / save_stall_avoid roundtrip")
    p = tmp_path / "soulseek-stall-avoid.json"
    avoid = {"SPOTID00001": {"congested", "other"}}
    S.save_stall_avoid(str(p), avoid)
    check("roundtrip survives", S.load_stall_avoid(str(p)) == avoid)
    check("missing file loads empty",
          S.load_stall_avoid(str(tmp_path / "nope.json")) == {})


def test_pick_candidate_respects_stall_avoid():
    print("pick_candidate: a persistently-avoided peer is skipped for that track")
    art, title = TRACK["artists"], TRACK["title"]
    resp = {"username": "congested",
            "files": [{"filename": f"m\\\\{art}\\\\01 {title}.mp3",
                       "length": 213, "bitRate": 320}]}
    resp_good = {"username": "goodpeer",
                 "files": [{"filename": f"f\\\\{art}\\\\02 {title}.flac",
                            "length": 215, "bitRate": 0}]}
    sid = TRACK["spotify_id"]
    avoid = {"SPOTID00001": {"congested"}}
    best = S.pick_candidate([resp, resp_good], art, title, 213000,
                            set(avoid.get(sid, ())), set())
    check("avoided peer is skipped in favour of a fresh peer", best[0] == "goodpeer")
    solo = S.pick_candidate([resp], art, title, 213000,
                            set(avoid.get(sid, ())), set())
    check("an avoided peer that is the only source -> no candidate", solo is None)


def test_expected_wait():
    print("expected_wait: the quick-alternate trigger reads free slot + queue length")
    check("a free upload slot is instant (0)",
          S.expected_wait({"hasFreeUploadSlot": True, "queueLength": 0}) == 0)
    check("a free slot stays instant even behind a long queue",
          S.expected_wait({"hasFreeUploadSlot": True, "queueLength": 45603}) == 0)
    check("a short queue is a plausible wait (1)",
          S.expected_wait({"queueLength": 5}) == 1)
    check("an unreported queue is not guessed congested (1)",
          S.expected_wait({}) == 1)
    check("a huge queue with no free slot is congested (2)",
          S.expected_wait({"queueLength": 20000}) == 2)
    check("exactly QUICK_QUEUE_LIMIT counts as congested",
          S.expected_wait({"queueLength": S.QUICK_QUEUE_LIMIT}) == 2)
    check("one below the limit is a plausible wait",
          S.expected_wait({"queueLength": S.QUICK_QUEUE_LIMIT - 1}) == 1)


def test_pick_candidate_quick_alternate():
    print("pick_candidate: a lesser version that will start now beats the most "
          "exact version parked behind a huge queue")
    art, title = TRACK["artists"], TRACK["title"]
    # The "best" version (exact length, richest bitrate) lives on a peer with a
    # 45,000-deep upload queue and no free slot. A weaker copy (closer length
    # mismatch, lower bitrate) sits on a peer with a free slot. The free-slot
    # peer must win: waiting weeks for the perfect copy is the freeze.
    exact = {"username": "congested",
             "queueLength": 45000,
             "files": [{"filename": f"m\\\\{art}\\\\01 {title}.flac",
                        "length": 213, "bitRate": 1411}]}
    quick = {"username": "freeslot", "hasFreeUploadSlot": True,
             "files": [{"filename": f"f\\\\{art}\\\\02 {title}.mp3",
                        "length": 215, "bitRate": 320}]}
    best = S.pick_candidate([exact, quick], art, title, 213000)
    check("the quick lesser copy beats the exact copy behind a huge queue",
          best is not None and best[0] == "freeslot")


def test_pick_candidate_quick_alternate_only_when_congested():
    print("pick_candidate: file exactness still decides within a wait class")
    art, title = TRACK["artists"], TRACK["title"]
    # Neither peer is congested: both report modest queues. The exact version
    # must still win -- the fallback only overrides exactness for a roundly
    # congested (wait-class-2) peer, never for an ordinary one.
    busy = {"username": "busy", "queueLength": 5,
            "files": [{"filename": f"m\\\\{art}\\\\01 {title}.mp3",
                       "length": 213, "bitRate": 320}]}
    other = {"username": "other", "queueLength": 3,
             "files": [{"filename": f"o\\\\{art}\\\\02 {title}.mp3",
                        "length": 215, "bitRate": 192}]}
    best = S.pick_candidate([busy, other], art, title, 213000)
    check("exact version still wins between two un-congested peers",
          best is not None and best[0] == "busy")


def test_stalled_transfer_no_place():
    print("stalled_transfer: a peer that reports no queue position freezes sooner")
    now = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    # No placeInQueue at all -- the silent-freeze signature. With no_place_hours
    # (the shorter bar) the transfer is flagged once it outstays it.
    silent = {"state": "Queued, Remotely",
              "enqueuedAt": "2026-07-31T14:00:00.000+00:00"}  # 10h before now
    check("a no-place transfer past the short bar is stalled",
          S.stalled_transfer(silent, now, 1000, 24, no_place_hours=8))
    fresh = {"state": "Queued, Remotely",
             "enqueuedAt": "2026-07-31T23:59:00.000+00:00"}  # 1 min before now
    check("a no-place transfer inside the short bar is not stalled",
          not S.stalled_transfer(fresh, now, 1000, 24, no_place_hours=8))
    # When no_place_hours is None it falls back to the regular stall bar.
    check("no_place_hours defaults to the regular bar",
          not S.stalled_transfer(silent, now, 1000, 24))
    check("actually out past the regular bar stalls too",
          S.stalled_transfer(
              {"state": "Queued, Remotely",
               "enqueuedAt": "2026-07-29T00:00:00.000+00:00"},
              now, 1000, 24))
    # A reported position is not affected by the no-place bar.
    pos = {"state": "Queued, Remotely", "placeInQueue": 5,
           "enqueuedAt": "2026-07-31T14:00:00.000+00:00"}
    check("a reported short position is judged by the regular bar",
          not S.stalled_transfer(pos, now, 1000, 24, no_place_hours=8))


def test_rescue_stalled_no_place():
    print("rescue_stalled: re-sources a no-position silent freeze")
    rows = [dict(TRACK)]
    state = {"SPOTID00001": queued("SPOTID00001", "silent", REJECTED_FILENAME)}
    rescued = set()
    avoid = {}
    now = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    # No placeInQueue key at all, parked 10h (past the 8h no-place bar).
    dl = dl_response({"username": "silent", "filename": REJECTED_FILENAME,
                      "state": "Queued, Remotely",
                      "enqueuedAt": "2026-07-31T14:00:00.000+00:00",
                      "id": "stall-np"})
    fake_http, saved = clear_state()
    orig = S.http
    S.http = fake_http
    try:
        blocked, n, rs_keys = S.rescue_stalled(
            rows, state, rescued, avoid, dl, now, "http://x", "k", dry_run=False,
            place_limit=1000, stall_hours=24, no_place_hours=8)
    finally:
        S.http = orig
    check("blocks the no-position peer", blocked == {"silent"})
    check("re-sources the track", n == 1)
    check("queued marker dropped", "SPOTID00001" not in state)
    check("congested peer remembered", avoid.get("SPOTID00001") == {"silent"})
    check("transfer id remembered", "stall-np" in rescued)
    deletes = [u for m, u in saved["calls"] if m == "DELETE"]
    check("cancels the frozen transfer with ?remove=true",
          len(deletes) == 1 and deletes[0].endswith("?remove=true"))


def test_requested_keys_dedup():
    print("requested_keys: same recording under a second entry is a duplicate")
    # Two missing.tsv rows, same recording, different spotify ids. One is
    # already queued; the other must be recognised as a duplicate of it.
    row_a = dict(TRACK, spotify_id="SID_A")
    row_b = dict(TRACK, spotify_id="SID_B", title="never gonna give you up")
    rows = [row_a, row_b]
    state = {"SID_A": queued("SID_A", "peer", REJECTED_FILENAME)}
    req = S.requested_keys(rows, state)
    check("queued row's keys are in the requested set",
          any(k in req for k in S.trackmatch.keys(row_a["artists"],
                                                  row_a["title"])))
    check("the SIBLING (other id, same song) folds into the same keys",
          any(k in req for k in S.trackmatch.keys(row_b["artists"],
                                                  row_b["title"])))
    # A different song is not swept in.
    other = {"artists": "Daft Punk", "title": "One More Time"}
    check("an unrelated song is not in the requested set",
          not any(k in req for k in S.trackmatch.keys(other["artists"],
                                                      other["title"])))
    # Only 'queued' status contributes; a nofind/error does not block re-search.
    state2 = {"SID_A": dict(queued("SID_A", "peer", REJECTED_FILENAME),
                            status="nofind")}
    check("a non-queued status contributes nothing",
          S.requested_keys(rows, state2) == set())


def test_acquire_lock_single_instance(tmp_path):
    print("acquire_lock: only one sweep may hold it")
    import fcntl
    saved = S._LOCK_FH
    try:
        first = S.acquire_lock(str(tmp_path))
        check("first caller takes the lock", first is True)
        # A second attempt (fresh fd, as a concurrent process would) is refused.
        path = os.path.join(str(tmp_path), "soulseek-missing.lock")
        fh2 = open(path, "w")
        busy = False
        try:
            fcntl.flock(fh2, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            busy = True
        finally:
            fh2.close()
        check("a second concurrent caller is refused", busy)
    finally:
        if S._LOCK_FH is not None:
            fcntl.flock(S._LOCK_FH, fcntl.LOCK_UN)
            S._LOCK_FH.close()
        S._LOCK_FH = saved


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
