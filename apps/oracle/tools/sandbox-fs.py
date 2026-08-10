#!/usr/bin/env python3
"""oracle's jailed filesystem executor — the muscle behind its file tools.

oracle offers the local ollama model a set of file tools (list/read/write/edit/
move/delete/mkdir; see apps/oracle/main.py `FILE_TOOLS`). Every one of them runs
THROUGH this script, and this script is the jail: it takes a single ROOT
directory as argv[1] and refuses to touch anything outside it, symlinks
included. That is the whole security model right now — the model gets a sandbox,
not the filesystem ("later we will let it run free maybe", his words, so the
jail root is one path, widened by pointing `ORACLE_SANDBOX` elsewhere).

WHERE it runs: oracle's compute is ollama on `top`, so the sandbox lives on top
too. On `top` oracle runs this locally; on `book` oracle runs it over the SAME
ssh master that tools/ollama-tunnel.sh already holds open — `ssh top python3
<this> <root>` — so the tools operate on top's filesystem regardless of which
machine the window is on. This file is pure stdlib on purpose: top's system
python3 runs it over ssh with nothing installed.

PROTOCOL: one JSON request object on stdin, one JSON result object on stdout.
    {"op": "read", "path": "notes.md", "offset": 0, "limit": 300}
    -> {"ok": true, "path": "notes.md", "content": "...", "start_line": 1, ...}
An error is `{"error": "<reason>"}` with exit 0 — the reason is fed back to the
model as the tool result, never a crash (docs/DESIGN.md §10: report, don't
silently fail). Results are CAPPED so a giant file or directory cannot blow the
model's context window (READ_MAX_LINES / READ_MAX_BYTES / LIST_MAX_ENTRIES).
"""
import json
import os
import shutil
import sys

# --- context caps: a tool result must never blow the model's context window ---
READ_MAX_LINES = 300      # default lines returned by one read (paginate for more)
READ_MAX_BYTES = 40000    # hard byte ceiling on a read's content, whatever the lines
READ_MAX_LINE = 1000      # a single line longer than this is truncated with a marker
LIST_MAX_ENTRIES = 200    # a directory listing is cut here, with `truncated: true`
WRITE_MAX_BYTES = 2_000_000   # refuse an absurd write outright


def fail(reason):
    print(json.dumps({"error": reason}))
    sys.exit(0)


def resolve(root, rel, *, must_exist):
    """Map a model-supplied path to an absolute path INSIDE the jail, or fail.

    Paths are always interpreted relative to the jail root (a leading `/` is
    stripped, not honoured as absolute). `os.path.realpath` collapses `..` and
    resolves every symlink in the chain, so a symlink pointing out of the jail
    resolves outside it and is rejected here — that is the escape guard."""
    rel = (rel or "").strip()
    if not rel or rel == ".":
        target = root
    else:
        target = os.path.normpath(os.path.join(root, rel.lstrip("/")))
    real = os.path.realpath(target)
    if real != root and not real.startswith(root + os.sep):
        fail("path escapes the sandbox: " + rel)
    if must_exist and not os.path.lexists(real):
        fail("no such path: " + rel)
    return real


def rel_to_root(root, path):
    r = os.path.relpath(path, root)
    return "." if r == "." else r


def op_list(root, req):
    d = resolve(root, req.get("path", "."), must_exist=True)
    if not os.path.isdir(d):
        fail("not a directory: " + req.get("path", "."))
    names = sorted(os.listdir(d), key=str.lower)
    total = len(names)
    entries = []
    for name in names[:LIST_MAX_ENTRIES]:
        p = os.path.join(d, name)
        try:
            st = os.lstat(p)
            if os.path.islink(p):
                kind = "link"
            elif os.path.isdir(p):
                kind = "dir"
            else:
                kind = "file"
            entries.append({"name": name, "type": kind,
                            "size": st.st_size if kind == "file" else None})
        except OSError:
            entries.append({"name": name, "type": "?", "size": None})
    return {"ok": True, "path": rel_to_root(root, d), "entries": entries,
            "count": total, "truncated": total > LIST_MAX_ENTRIES}


def op_read(root, req):
    p = resolve(root, req.get("path", ""), must_exist=True)
    if os.path.isdir(p):
        fail("is a directory (use list_dir): " + req.get("path", ""))
    try:
        raw = open(p, "rb").read()
    except OSError as e:
        fail("cannot read: " + str(e))
    if b"\x00" in raw[:8192]:
        return {"ok": True, "path": rel_to_root(root, p), "binary": True,
                "bytes": len(raw), "content": "",
                "note": "binary file, not shown"}
    text = raw.decode("utf-8", "replace")
    lines = text.splitlines()
    total = len(lines)
    try:
        offset = max(0, int(req.get("offset", 0) or 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(req.get("limit", READ_MAX_LINES) or READ_MAX_LINES)
    except (TypeError, ValueError):
        limit = READ_MAX_LINES
    limit = max(1, min(limit, READ_MAX_LINES))
    chunk = lines[offset:offset + limit]
    out, nbytes, cut_bytes = [], 0, False
    for ln in chunk:
        if len(ln) > READ_MAX_LINE:
            ln = ln[:READ_MAX_LINE] + " …[line truncated]"
        if nbytes + len(ln) + 1 > READ_MAX_BYTES:
            cut_bytes = True
            break
        out.append(ln)
        nbytes += len(ln) + 1
    shown = len(out)
    end = offset + shown
    return {"ok": True, "path": rel_to_root(root, p),
            "content": "\n".join(out),
            "start_line": offset + 1 if shown else 0,
            "end_line": end, "total_lines": total,
            "truncated": end < total or cut_bytes,
            "next_offset": end if end < total else None}


def op_write(root, req):
    content = req.get("content", "")
    if not isinstance(content, str):
        fail("content must be a string")
    data = content.encode("utf-8")
    if len(data) > WRITE_MAX_BYTES:
        fail("refusing to write %d bytes (cap %d)" % (len(data), WRITE_MAX_BYTES))
    p = resolve(root, req.get("path", ""), must_exist=False)
    if os.path.isdir(p):
        fail("is a directory: " + req.get("path", ""))
    existed = os.path.exists(p)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
    except OSError as e:
        fail("cannot write: " + str(e))
    return {"ok": True, "path": rel_to_root(root, p), "bytes": len(data),
            "created": not existed}


def op_edit(root, req):
    old = req.get("old", "")
    new = req.get("new", "")
    if not isinstance(old, str) or not isinstance(new, str):
        fail("old and new must be strings")
    if old == "":
        fail("old must be a non-empty string (use write_file to create/replace)")
    p = resolve(root, req.get("path", ""), must_exist=True)
    if os.path.isdir(p):
        fail("is a directory: " + req.get("path", ""))
    try:
        text = open(p, "rb").read().decode("utf-8", "replace")
    except OSError as e:
        fail("cannot read: " + str(e))
    n = text.count(old)
    if n == 0:
        fail("old string not found in " + req.get("path", ""))
    replace_all = bool(req.get("replace_all", False))
    if n > 1 and not replace_all:
        fail("old string is not unique (%d matches); pass replace_all or add context" % n)
    text = text.replace(old, new)
    data = text.encode("utf-8")
    if len(data) > WRITE_MAX_BYTES:
        fail("edit would exceed the write cap")
    try:
        with open(p, "wb") as f:
            f.write(data)
    except OSError as e:
        fail("cannot write: " + str(e))
    return {"ok": True, "path": rel_to_root(root, p),
            "replacements": n if replace_all else 1}


def op_move(root, req):
    src = resolve(root, req.get("src", ""), must_exist=True)
    dst = resolve(root, req.get("dst", ""), must_exist=False)
    if os.path.exists(dst) and os.path.isdir(dst) and not os.path.isdir(src):
        dst = os.path.join(dst, os.path.basename(src))
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
    except (OSError, shutil.Error) as e:
        fail("cannot move: " + str(e))
    return {"ok": True, "src": rel_to_root(root, src),
            "dst": rel_to_root(root, dst)}


def op_delete(root, req):
    p = resolve(root, req.get("path", ""), must_exist=True)
    if p == root:
        fail("refusing to delete the sandbox root itself")
    recursive = bool(req.get("recursive", False))
    try:
        if os.path.isdir(p) and not os.path.islink(p):
            if os.listdir(p) and not recursive:
                fail("directory not empty (pass recursive to delete it)")
            if recursive:
                shutil.rmtree(p)
            else:
                os.rmdir(p)
        else:
            os.remove(p)
    except OSError as e:
        fail("cannot delete: " + str(e))
    return {"ok": True, "path": rel_to_root(root, p)}


def op_mkdir(root, req):
    p = resolve(root, req.get("path", ""), must_exist=False)
    try:
        os.makedirs(p, exist_ok=True)
    except OSError as e:
        fail("cannot create directory: " + str(e))
    return {"ok": True, "path": rel_to_root(root, p)}


OPS = {"list": op_list, "read": op_read, "write": op_write, "edit": op_edit,
       "move": op_move, "delete": op_delete, "mkdir": op_mkdir}


def main():
    if len(sys.argv) < 2:
        fail("no sandbox root given")
    root = os.path.realpath(os.path.expanduser(sys.argv[1]))
    try:
        os.makedirs(root, exist_ok=True)   # a fresh top has no sandbox yet
    except OSError as e:
        fail("cannot create sandbox root: " + str(e))
    try:
        req = json.loads(sys.stdin.read() or "{}")
        if not isinstance(req, dict):
            raise ValueError
    except ValueError:
        fail("bad request")
    op = OPS.get(req.get("op", ""))
    if op is None:
        fail("unknown op: " + str(req.get("op", "")))
    try:
        print(json.dumps(op(root, req)))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — never crash into the model's face
        fail("file tool error: " + str(e))


if __name__ == "__main__":
    main()
