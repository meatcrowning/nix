#!/usr/bin/env python3
"""oracle's memory store — the muscle behind the memories it manages itself.

Distinct from the SESSION store (tools/sessions-store.py): a session is a whole
past transcript oracle can READ; a memory is one durable FACT oracle deliberately
WROTE — a persistent note it keeps across conversations, creates/edits/deletes on
its own, and is fed back to it as real context on later turns (analogous to the
board / Claude-memory pattern: one fact per entry with a shared index). Every
store operation runs THROUGH this script, exactly like the session and file
stores: it takes a single ROOT directory as argv[1] and holds ONE JSON file,
`memories.json`, under it — a list of
{id,text,source_quote,created,updated} entries. Old entries without a quote are
kept as legacy/unverified memories; the app labels them that way.

WHERE it runs: like the session store, oracle keeps ONE canonical store so the
two machines share one set of memories rather than a per-machine split. oracle's
compute is ollama on `top`, so the store lives there too — on `top` oracle runs
this locally; on `book` it runs over the SAME ssh master tools/ollama-tunnel.sh
holds open. This file is pure stdlib on purpose: top's system python3 runs it
over ssh with nothing installed.

PROTOCOL: one JSON request object on stdin, one JSON result object on stdout.
    {"op": "list"}
    -> {"memories": [{"id","text","created","updated"}, ...]}   (newest-updated first)
    {"op": "save", "text": "…", "id"?: "mem-…"}
    -> {"ok": true, "memory": {"id","text","created","updated"}}
       (no id -> mint a fresh one; an id that exists -> update its text)
    {"op": "delete", "id": "mem-…"}
    -> {"ok": true}
An error is `{"error": "<reason>"}` with exit 0 — the reason is surfaced to oracle
and shown, never a crash (docs/DESIGN.md §10: report, don't silently fail). Unlike
the session store, the memory id IS minted here (a `mem-<ms>-<rand>` token) when a
save carries none, so a create is one round-trip.
"""
import json
import os
import random
import re
import sys
import time

#: A memory id is a bare token — minted here or handed back on an update. Guard
#: it so nothing crafted can matter (the store is a single file, but keep the
#: shape strict anyway, matching the session store's discipline).
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
STORE_NAME = "memories.json"
TEXT_MAX = 4000          # one memory is a fact, not a document; clip a runaway
ENTRIES_MAX = 500        # cap the whole store so it can never blow the context


def fail(reason):
    print(json.dumps({"error": reason}))
    sys.exit(0)


def store_path(root):
    return os.path.join(root, STORE_NAME)


def load_all(root):
    """The whole memory list, or [] if the store is absent/corrupt (never crash —
    a corrupt store reads as empty rather than taking the app down)."""
    try:
        obj = json.loads(open(store_path(root), encoding="utf-8").read() or "{}")
    except (OSError, ValueError):
        return []
    if isinstance(obj, dict):
        obj = obj.get("memories", [])
    if not isinstance(obj, list):
        return []
    out = []
    for e in obj:
        if isinstance(e, dict) and e.get("id"):
            out.append(e)
    return out


def write_all(root, entries):
    try:
        os.makedirs(root, exist_ok=True)
        p = store_path(root)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"memories": entries}, fh, ensure_ascii=False)
        os.replace(tmp, p)            # atomic, so a reader never sees a half-write
    except OSError as e:
        fail("could not write memory store: " + str(e))


def mint_id():
    return "mem-%d-%04x" % (int(time.time() * 1000), random.getrandbits(16))


def op_list(root):
    entries = load_all(root)
    entries.sort(key=lambda e: e.get("updated", 0), reverse=True)
    return {"memories": [
        {"id": e.get("id"), "text": e.get("text", ""),
         "source_quote": e.get("source_quote", ""),
         "created": e.get("created", 0), "updated": e.get("updated", 0)}
        for e in entries]}


def op_save(root, req):
    text = str(req.get("text", "")).strip()
    source_quote = str(req.get("source_quote", "")).strip()
    if not text:
        fail("save needs non-empty text")
    if not source_quote:
        fail("save needs a quote from the user's current message")
    if len(text) > TEXT_MAX:
        text = text[:TEXT_MAX]
    now = int(time.time())
    entries = load_all(root)
    sid = req.get("id")
    if sid:                               # update an existing memory
        if not ID_RE.match(str(sid)):
            fail("bad memory id: " + str(sid))
        for e in entries:
            if e.get("id") == sid:
                e["text"] = text
                e["source_quote"] = source_quote
                e["updated"] = now
                write_all(root, entries)
                return {"ok": True, "memory": {
                    "id": sid, "text": text, "source_quote": source_quote,
                    "created": e.get("created", now), "updated": now}}
        fail("no such memory: " + str(sid))
    # create — mint an id and prepend
    if len(entries) >= ENTRIES_MAX:       # drop the oldest-updated to make room
        entries.sort(key=lambda e: e.get("updated", 0), reverse=True)
        entries = entries[:ENTRIES_MAX - 1]
    new_id = mint_id()
    entry = {"id": new_id, "text": text, "source_quote": source_quote,
             "created": now, "updated": now}
    entries.append(entry)
    write_all(root, entries)
    return {"ok": True, "memory": entry}


def op_delete(root, req):
    sid = str(req.get("id", ""))
    if not ID_RE.match(sid):
        fail("bad memory id: " + sid)
    entries = load_all(root)
    kept = [e for e in entries if e.get("id") != sid]
    if len(kept) != len(entries):
        write_all(root, kept)
    return {"ok": True}


def main():
    if len(sys.argv) < 2:
        fail("usage: memory-store.py <root>  (JSON request on stdin)")
    root = os.path.realpath(os.path.expanduser(sys.argv[1]))
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        fail("request is not valid JSON")
    if not isinstance(req, dict):
        fail("request must be a JSON object")
    op = req.get("op", "")
    handler = {"list": lambda: op_list(root),
               "save": lambda: op_save(root, req),
               "delete": lambda: op_delete(root, req)}.get(op)
    if handler is None:
        fail("unknown op: " + str(op))
    print(json.dumps(handler(), ensure_ascii=False))


if __name__ == "__main__":
    main()
