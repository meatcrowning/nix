#!/usr/bin/env python3
"""oracle's jailed filesystem executor — the muscle behind its file tools.

oracle offers the local ollama model a set of file tools (list/read/write/edit/
move/delete/mkdir, plus the search ops glob/grep/tree, `image`, which hands a
local picture back base64 for a vision model to LOOK at, and `audio`, which cuts
a bounded excerpt for an audio model to LISTEN to; see apps/oracle/main.py
`FILE_TOOLS`). Every one of them runs
THROUGH this script, and this script is the jail: it takes a WRITE root as
argv[1] and refuses to write, edit, move or delete anything outside it, symlinks
included. The MUTATING ops stay jailed to that sandbox; the READ-ONLY ops
(list/read/glob/grep/tree — see READ_OPS) resolve against an optional wider READ
root passed as argv[2], so the model gets read access to the FULL filesystem
(root '/', his ask, widened 2026-08-11 from just his home) while writes cannot
escape the sandbox. Both roots are widened/narrowed by pointing `ORACLE_SANDBOX`
/ `ORACLE_READ_ROOT` elsewhere; with no argv[2] the read ops fall back to the
write root (older executor, one-path behaviour — the fallback a caller relies
on when the OTHER host hasn't pulled the argv[2] change yet).

WHERE it runs: THIS invocation runs on whichever host it was started on — that
is the whole point. The WRITE root (sandbox) only ever exists on `top`, so
mutating ops always run there: locally when oracle's window IS top, over the
ssh master tools/ollama-tunnel.sh already holds open when it is book. The
READ-ONLY ops can target EITHER machine: oracle's main.py (`Ollama._fs_argv`)
picks which host to invoke THIS script on per read call — local when it's the
same machine the window runs on, a fresh ssh call over the tailnet (both
directions: `ssh top` from book, `ssh book` from top) otherwise — so the model
can read book's filesystem from a top window and top's from a book window. This
file is pure stdlib on purpose: the target's system python3 runs it over ssh
with nothing installed.

PROTOCOL: one JSON request object on stdin, one JSON result object on stdout.
    {"op": "read", "path": "notes.md", "offset": 0, "limit": 300}
    -> {"ok": true, "path": "notes.md", "content": "...", "start_line": 1, ...}
An error is `{"error": "<reason>"}` with exit 0 — the reason is fed back to the
model as the tool result, never a crash (docs/DESIGN.md §10: report, don't
silently fail). Results are CAPPED so a giant file or directory cannot blow the
model's context window (READ_MAX_LINES / READ_MAX_BYTES / LIST_MAX_ENTRIES).
"""
import base64
import binascii
import fnmatch
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from datetime import datetime, timezone

# --- context caps: a tool result must never blow the model's context window ---
READ_MAX_LINES = 300      # default lines returned by one read (paginate for more)
READ_MAX_BYTES = 40000    # hard byte ceiling on a read's content, whatever the lines
READ_MAX_LINE = 1000      # a single line longer than this is truncated with a marker
LIST_MAX_ENTRIES = 200    # a directory listing is cut here, with `truncated: true`
WRITE_MAX_BYTES = 2_000_000   # refuse an absurd write outright
GLOB_MAX_ENTRIES = 300    # a glob's match list is cut here, with `truncated: true`
GREP_MAX_MATCHES = 200    # a content search stops after this many matching lines
GREP_MAX_FILES = 5000     # ...and never scans more files than this (runaway guard)
GREP_MAX_LINE = 400       # a matching line longer than this is truncated in the result
TREE_MAX_ENTRIES = 400    # a tree is cut here, with `truncated: true`
TREE_MAX_DEPTH = 5        # how deep a tree descends by default (and its hard ceiling)


def fail(reason):
    print(json.dumps({"error": reason}))
    sys.exit(0)


def _under(root, path):
    """True iff `path` is exactly `root` or lives under it, as plain strings.

    `root + os.sep` is the obvious containment prefix, except when root IS the
    filesystem root ("/"): then it is "//", which no absolute path starts
    with, so a jail widened to "/" (his ask, 2026-08-11) rejected every read
    with "path escapes the sandbox" until this normalizes the root to already
    carry its trailing separator first."""
    root_with_sep = root if root.endswith(os.sep) else root + os.sep
    return path == root or path.startswith(root_with_sep)


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
    if not _under(root, real):
        fail("path escapes the sandbox: " + rel)
    if must_exist and not os.path.lexists(real):
        fail("no such path: " + rel)
    return real


def rel_to_root(root, path):
    r = os.path.relpath(path, root)
    return "." if r == "." else r


def contained(root, path):
    """True iff `path`, symlinks resolved, is the jail root or lives under it.

    The escape guard for the walking ops (grep/glob/tree): they descend with
    os.walk(followlinks=False) so a symlinked DIRECTORY is never entered, but a
    symlinked FILE could still resolve outside the jail, so every candidate is
    checked here before it is read or reported — same realpath test `resolve`
    uses, never weakened."""
    return _under(root, os.path.realpath(path))


def _is_binary(path):
    """A file is treated as binary (skipped by grep) if its first block has a
    NUL byte — the same cheap test op_read uses before dumping a file."""
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(8192)
    except OSError:
        return True


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


#: The biggest image the `view_image` tool will hand back, in BYTES before
#: base64. It rides the same ceiling a dropped attachment gets (main.py
#: ATTACH_IMAGE_MAX): past this the model is told the size rather than the
#: window spending 30 MB of context on one picture.
IMAGE_MAX_BYTES = 8 * 1024 * 1024

#: The raster types a vision model accepts, by MAGIC BYTES — never the
#: extension (main.py `_sniff_image` carries the same table for dropped files).
IMAGE_MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"),
               (b"\xff\xd8\xff", "image/jpeg"),
               (b"GIF87a", "image/gif"),
               (b"GIF89a", "image/gif"))


def op_image(root, req):
    """Read an IMAGE file and hand it back base64, for the model to look at.

    The same read jail as every other read op, so `view_image` can reach
    anything the model could already `read_file` and nothing more. Only real
    raster images come back (sniffed, never trusted to the extension), and only
    up to IMAGE_MAX_BYTES — the point is a picture the model can see, not a
    channel for arbitrary bytes.
    """
    p = resolve(root, req.get("path", ""), must_exist=True)
    if os.path.isdir(p):
        fail("is a directory: " + req.get("path", ""))
    try:
        size = os.path.getsize(p)
    except OSError as e:
        fail("cannot read: " + str(e))
    if size > IMAGE_MAX_BYTES:
        fail("image is %d MB, over the %d MB limit"
             % (size // (1024 * 1024), IMAGE_MAX_BYTES // (1024 * 1024)))
    try:
        raw = open(p, "rb").read()
    except OSError as e:
        fail("cannot read: " + str(e))
    media = ""
    for magic, mt in IMAGE_MAGIC:
        if raw.startswith(magic):
            media = mt
            break
    if not media and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        media = "image/webp"
    if not media:
        fail("not an image this model can look at (png, jpeg, gif or webp): "
             + req.get("path", ""))
    return {"ok": True, "path": rel_to_root(root, p), "media": media,
            "bytes": len(raw),
            "b64": base64.b64encode(raw).decode("ascii")}


#: LISTENING (op `audio`, main.py `listen_audio`). The excerpt is cut WHERE THE
#: FILE IS — that is the whole reason this lives in the executor rather than in
#: the window: a 40 MB flac on top would otherwise cross the tailnet to be
#: trimmed on book. What comes back is a bounded 16 kHz mono wav, because a
#: second of audio costs the model ~25 prompt tokens whatever the source rate,
#: so a whole album track is most of a small window and says no more than a
#: chorus does.
AUDIO_MAX_SECONDS = 180        # hard ceiling on one excerpt, whatever is asked
AUDIO_DEFAULT_SECONDS = 30
AUDIO_RATE = 16000


def _duration(p):
    """The file's length in seconds via ffprobe, or 0 when it cannot say."""
    exe = shutil.which("ffprobe")
    if not exe:
        return 0
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", "--", p],
            capture_output=True, timeout=20)
        return round(float(out.stdout.decode("utf-8", "replace").strip()), 1)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def _wav_sized(raw):
    """A wav ffmpeg wrote to a PIPE, with its real length stamped in.

    ffmpeg cannot seek back on stdout, so it leaves 0xFFFFFFFF placeholders in
    the RIFF and `data` size fields — a header claiming 34 hours. Patched here
    to what actually arrived (main.py keeps the same fix for the clips it cuts
    itself; this script stays stdlib-only and cannot share it).
    """
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return raw
    out = bytearray(raw)
    out[4:8] = struct.pack("<I", len(out) - 8)
    pos = 12
    while pos + 8 <= len(out):
        cid = bytes(out[pos:pos + 4])
        size = struct.unpack("<I", bytes(out[pos + 4:pos + 8]))[0]
        body = len(out) - (pos + 8)
        if cid == b"data" and (size > body or size == 0):
            out[pos + 4:pos + 8] = struct.pack("<I", body)
            break
        if size > body:
            break
        pos += 8 + size + (size & 1)
    return bytes(out)


def op_audio(root, req):
    """Cut a bounded excerpt out of an audio (or video) file and hand it back
    base64, for an audio-capable model to LISTEN to.

    The same read jail as every other read op, so `listen_audio` reaches
    exactly what the model could already `read_file` and nothing more. ffmpeg
    does the trim and the downmix; absent, the op FAILS with a reason rather
    than handing back a 44.1 kHz stereo album track (docs/DESIGN.md §10).
    """
    p = resolve(root, req.get("path", ""), must_exist=True)
    if os.path.isdir(p):
        fail("is a directory: " + req.get("path", ""))
    try:
        seconds = float(req.get("seconds") or AUDIO_DEFAULT_SECONDS)
    except (TypeError, ValueError):
        seconds = float(AUDIO_DEFAULT_SECONDS)
    seconds = max(1.0, min(seconds, float(AUDIO_MAX_SECONDS)))
    try:
        start = max(0.0, float(req.get("start") or 0))
    except (TypeError, ValueError):
        start = 0.0
    try:
        rate = int(req.get("rate") or AUDIO_RATE)
    except (TypeError, ValueError):
        rate = AUDIO_RATE
    exe = shutil.which("ffmpeg")
    if not exe:
        fail("ffmpeg is not installed on this machine, so the audio cannot be "
             "trimmed to something a model can hear")
    dur = _duration(p)
    # A start past the end is a silent wav and a confused model; say so.
    if dur and start >= dur:
        fail("that file is only %.1fs long, so there is nothing at %.1fs"
             % (dur, start))
    argv = [exe, "-v", "error", "-nostdin"]
    if start > 0:
        argv += ["-ss", "%.3f" % start]
    argv += ["-t", "%.3f" % seconds, "-i", p, "-map", "0:a:0", "-vn",
             "-ar", str(rate), "-ac", "1", "-c:a", "pcm_s16le", "-f", "wav", "-"]
    try:
        out = subprocess.run(argv, capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        fail("ffmpeg could not read that file: " + str(e))
    if out.returncode != 0 or len(out.stdout) <= 44:
        why = out.stderr.decode("utf-8", "replace").strip().splitlines()
        fail(why[-1][:200] if why else "no audio stream in that file")
    wav = _wav_sized(out.stdout)
    got = round((len(wav) - 44) / float(rate * 2), 1)
    return {"ok": True, "path": rel_to_root(root, p), "media": "audio/wav",
            "bytes": len(wav), "start": round(start, 1),
            "seconds": got, "duration": dur,
            "b64": base64.b64encode(wav).decode("ascii")}


#: What a file IS, sniffed from its first bytes — never from its extension,
#: which is a claim and not a fact (the same rule op_image follows). Only the
#: shapes worth naming to a model; anything else comes back as text or bytes.
FILE_MAGIC = (
    (b"%PDF-", "application/pdf"), (b"PK\x03\x04", "application/zip"),
    (b"\x1f\x8b", "application/gzip"), (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (b"ID3", "audio/mpeg"), (b"fLaC", "audio/flac"), (b"OggS", "application/ogg"),
    (b"RIFF", "audio/wav"), (b"\x7fELF", "application/x-executable"),
    (b"SQLite format 3", "application/vnd.sqlite3"),
    (b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"), (b"BM", "image/bmp"),
)

#: How much of a media file's ffprobe result is worth a model's context. A raw
#: `-show_streams` on a video runs to hundreds of lines of side data.
META_MAX_STREAMS = 8
META_MAX_TAGS = 24
META_TAG_CHARS = 300
META_TEXT_MAX_BYTES = 64 << 20   # past this a line/word count is not worth the read


def _stamp(epoch):
    """One timestamp shape for every op that reports a time: local ISO to the
    minute, which is what a model can quote back at him without conversion."""
    try:
        return datetime.fromtimestamp(epoch, timezone.utc).astimezone().isoformat(
            timespec="minutes")
    except (OSError, OverflowError, ValueError):
        return ""


def _sniff_kind(p):
    """(media_type, head_bytes) for one file, by MAGIC."""
    try:
        head = open(p, "rb").read(64)
    except OSError:
        return "", b""
    if head[4:12] == b"ftypisom" or head[4:8] == b"ftyp":
        return "video/mp4", head
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", head
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "video/x-msvideo", head
    if head[:4] == b"\x1aE\xdf\xa3":
        return "video/x-matroska", head
    for magic, mt in FILE_MAGIC:
        if head.startswith(magic):
            return mt, head
    return "", head


def _ffprobe(p):
    """ffprobe's format+streams for one file, projected down to what is worth
    saying. Returns {} when ffprobe is absent (this script is stdlib-only and
    runs on whatever host it landed on) or when the file is not media."""
    exe = shutil.which("ffprobe")
    if not exe:
        return {}
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-print_format", "json", "-show_format",
             "-show_streams", "--", p],
            capture_output=True, timeout=20)
        info = json.loads(out.stdout.decode("utf-8", "replace") or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    if not isinstance(info, dict):
        return {}

    def tags(d):
        t = d.get("tags") or {}
        if not isinstance(t, dict):
            return {}
        return {k.lower(): str(v)[:META_TAG_CHARS]
                for k, v in list(t.items())[:META_MAX_TAGS]}

    fmt = info.get("format") or {}
    out = {}
    if fmt.get("format_long_name") or fmt.get("format_name"):
        out["container"] = fmt.get("format_long_name") or fmt.get("format_name")
    for key, name in (("duration", "duration_seconds"), ("bit_rate", "bit_rate")):
        try:
            if fmt.get(key) is not None:
                out[name] = round(float(fmt[key]), 3)
        except (TypeError, ValueError):
            pass
    if tags(fmt):
        out["tags"] = tags(fmt)
    streams = []
    for st in (info.get("streams") or [])[:META_MAX_STREAMS]:
        one = {"type": st.get("codec_type") or "?",
               "codec": st.get("codec_name") or ""}
        for k in ("width", "height", "sample_rate", "channels", "bit_rate",
                  "pix_fmt", "profile", "r_frame_rate", "duration"):
            if st.get(k) not in (None, ""):
                one[k] = st[k]
        if tags(st):
            one["tags"] = tags(st)
        streams.append(one)
    if streams:
        out["streams"] = streams
    return out


def op_meta(root, req):
    """What a file IS, without reading it: size, times, type, and — for media —
    its container, duration, codecs, dimensions and TAGS.

    A read op (same wide read root), and the answer `read_file` cannot give: a
    3-minute flac is bytes to `read`, and a model asked "how long is this / what
    bitrate / who is the artist" had to guess from the filename. ffprobe does
    the media half when it is on the target host; everything else here is
    stdlib, so this still answers over ssh on a machine with nothing installed.
    """
    p = resolve(root, req.get("path", ""), must_exist=True)
    try:
        st = os.stat(p)
    except OSError as e:
        fail("cannot stat: " + str(e))
    out = {"ok": True, "path": rel_to_root(root, p),
           "name": os.path.basename(p),
           "bytes": st.st_size,
           "modified": _stamp(st.st_mtime),
           "mode": oct(st.st_mode & 0o7777)[2:].rjust(4, "0")}
    if os.path.isdir(p):
        try:
            kids = os.listdir(p)
        except OSError as e:
            fail("cannot read: " + str(e))
        out["kind"] = "directory"
        out["entries"] = len(kids)
        return out
    out["kind"] = "file"
    media, head = _sniff_kind(p)
    if media:
        out["media_type"] = media
    if not _is_binary(p):
        out["media_type"] = out.get("media_type") or "text/plain"
        # Counted over the WHOLE file, streaming: a capped count is a WRONG
        # count, and "3062 lines" of a 5904-line file is worse than no number.
        try:
            lines, words, seen, last = 0, 0, 0, b"\n"
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    if seen > META_TEXT_MAX_BYTES:
                        out["counts_partial"] = True
                        break
                    seen += len(chunk)
                    lines += chunk.count(b"\n")
                    words += len(chunk.split())
                    last = chunk[-1:] or last
            out["lines"] = lines + (1 if last != b"\n" else 0)
            out["words"] = words
        except OSError:
            pass
    probe = _ffprobe(p)
    if probe:
        out.update(probe)
    if req.get("hash"):
        try:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out["sha256"] = h.hexdigest()
        except OSError as e:
            out["sha256_error"] = str(e)
    return out


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


def op_put(root, req):
    """Stage raw bytes into the sandbox: decode base64 `data` and write it at
    `path`. Not a model tool — it has no schema in FILE_TOOLS and no name in
    FILE_OP, so a model cannot call it; oracle's OWN attachment-staging code
    (main.py `_stage_attachments`) uses it to drop a file the user dragged onto
    the window INTO the sandbox, so the model's read/edit/write tools can then
    reach the full file. Same jail (`resolve`) and same write cap as op_write,
    but binary-safe (op_write only takes UTF-8 text)."""
    data_b64 = req.get("data", "")
    if not isinstance(data_b64, str):
        fail("data must be a base64 string")
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (ValueError, binascii.Error):
        fail("data is not valid base64")
    if len(data) > WRITE_MAX_BYTES:
        fail("refusing to stage %d bytes (cap %d)" % (len(data), WRITE_MAX_BYTES))
    p = resolve(root, req.get("path", ""), must_exist=False)
    if os.path.isdir(p):
        fail("is a directory: " + req.get("path", ""))
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
    except OSError as e:
        fail("cannot stage: " + str(e))
    return {"ok": True, "path": rel_to_root(root, p), "bytes": len(data)}


def op_glob(root, req):
    """Find files/dirs by shell glob, sandbox-relative. `**` recurses. Results
    are the matching paths (relative to the root), capped."""
    base = resolve(root, req.get("path", "."), must_exist=True)
    if not os.path.isdir(base):
        fail("not a directory: " + req.get("path", "."))
    pattern = (req.get("pattern") or "").strip()
    if not pattern:
        fail("pattern is required")
    matches, total = [], 0
    # os.walk keeps the descent inside the jail (followlinks=False), then each
    # candidate name is fnmatched against the pattern relative to the base.
    recursive = "**" in pattern
    pat = pattern.replace("**/", "").replace("**", "*") if recursive else pattern
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames.sort(key=str.lower)
        for name in sorted(filenames + dirnames, key=str.lower):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base)
            hay = rel if recursive else name
            if not fnmatch.fnmatch(hay, pat):
                continue
            if not contained(root, full):
                continue
            total += 1
            if len(matches) < GLOB_MAX_ENTRIES:
                kind = "dir" if os.path.isdir(full) else (
                    "link" if os.path.islink(full) else "file")
                matches.append({"path": rel_to_root(root, full), "type": kind})
        if not recursive:
            del dirnames[:]        # a non-recursive glob is one level only
    return {"ok": True, "path": rel_to_root(root, base), "pattern": pattern,
            "matches": matches, "count": total,
            "truncated": total > GLOB_MAX_ENTRIES}


def op_grep(root, req):
    """Search file CONTENTS for a regex, sandbox-relative. Optionally restrict to
    files matching `glob`. Binary files are skipped; matches are capped."""
    pattern = req.get("pattern") or ""
    if not pattern:
        fail("pattern is required")
    try:
        rx = re.compile(pattern, re.IGNORECASE if req.get("ignore_case") else 0)
    except re.error as e:
        fail("bad regex: " + str(e))
    base = resolve(root, req.get("path", "."), must_exist=True)
    file_glob = (req.get("glob") or "").strip()
    matches, files_scanned, files_matched = [], 0, 0
    truncated_hits = truncated_scan = False

    def search_file(full):
        nonlocal files_scanned, files_matched, truncated_hits, truncated_scan
        if not contained(root, full) or _is_binary(full):
            return
        files_scanned += 1
        if files_scanned > GREP_MAX_FILES:
            truncated_scan = True
            return
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                hit = False
                for n, line in enumerate(f, 1):
                    if rx.search(line):
                        hit = True
                        if len(matches) < GREP_MAX_MATCHES:
                            text = line.rstrip("\n")
                            if len(text) > GREP_MAX_LINE:
                                text = text[:GREP_MAX_LINE] + " …[truncated]"
                            matches.append({"path": rel_to_root(root, full),
                                            "line": n, "text": text})
                        else:
                            truncated_hits = True
                if hit:
                    files_matched += 1
        except OSError:
            return

    if os.path.isdir(base):
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames.sort(key=str.lower)
            for name in sorted(filenames, key=str.lower):
                if file_glob and not fnmatch.fnmatch(name, file_glob):
                    continue
                search_file(os.path.join(dirpath, name))
                if truncated_scan:
                    break
            if truncated_scan:
                break
    else:
        search_file(base)
    return {"ok": True, "path": rel_to_root(root, base), "pattern": pattern,
            "matches": matches, "match_count": len(matches),
            "files_matched": files_matched, "files_scanned": files_scanned,
            "truncated": truncated_hits or truncated_scan}


def op_tree(root, req):
    """Render the directory structure under a path as an indented tree, depth-
    and entry-capped so a deep tree never blows the context window."""
    base = resolve(root, req.get("path", "."), must_exist=True)
    if not os.path.isdir(base):
        fail("not a directory: " + req.get("path", "."))
    try:
        max_depth = int(req.get("depth", TREE_MAX_DEPTH) or TREE_MAX_DEPTH)
    except (TypeError, ValueError):
        max_depth = TREE_MAX_DEPTH
    max_depth = max(1, min(max_depth, TREE_MAX_DEPTH))
    lines, count = [rel_to_root(root, base)], 0
    truncated = [False]

    def walk(d, depth, prefix):
        if depth > max_depth or truncated[0]:
            return
        try:
            names = sorted(os.listdir(d), key=str.lower)
        except OSError:
            return
        for name in names:
            if count >= TREE_MAX_ENTRIES:
                truncated[0] = True
                return
            full = os.path.join(d, name)
            is_dir = os.path.isdir(full) and not os.path.islink(full)
            mark = "/" if is_dir else ("@" if os.path.islink(full) else "")
            lines.append(prefix + name + mark)
            _bump()
            if is_dir and depth < max_depth and contained(root, full):
                walk(full, depth + 1, prefix + "  ")

    def _bump():
        nonlocal count
        count += 1

    walk(base, 1, "  ")
    return {"ok": True, "path": rel_to_root(root, base), "depth": max_depth,
            "tree": "\n".join(lines), "count": count, "truncated": truncated[0]}


OPS = {"list": op_list, "read": op_read, "write": op_write, "edit": op_edit,
       "move": op_move, "delete": op_delete, "mkdir": op_mkdir, "put": op_put,
       "glob": op_glob, "grep": op_grep, "tree": op_tree,
       "image": op_image, "meta": op_meta, "audio": op_audio}

# The READ-ONLY ops. They may reach a WIDER root than the mutating ops: the
# model gets read access to the whole filesystem, root '/' (his ask,
# 2026-08-11) while writes stay confined to the sandbox. argv[1] is the WRITE
# root (the sandbox); an optional argv[2] is the READ root ('/' by default).
# Absent argv[2], read ops fall back to the write root — so an older executor
# over ssh (the OTHER host not yet pulled) just keeps the old jailed-both
# behaviour rather than breaking.
READ_OPS = {"list", "read", "glob", "grep", "tree", "image", "meta", "audio"}


def main():
    if len(sys.argv) < 2:
        fail("no sandbox root given")
    write_root = os.path.realpath(os.path.expanduser(sys.argv[1]))
    read_root = (os.path.realpath(os.path.expanduser(sys.argv[2]))
                 if len(sys.argv) > 2 and sys.argv[2] else write_root)
    try:
        os.makedirs(write_root, exist_ok=True)   # a fresh top has no sandbox yet
    except OSError as e:
        fail("cannot create sandbox root: " + str(e))
    try:
        req = json.loads(sys.stdin.read() or "{}")
        if not isinstance(req, dict):
            raise ValueError
    except ValueError:
        fail("bad request")
    opname = req.get("op", "")
    op = OPS.get(opname)
    if op is None:
        fail("unknown op: " + str(opname))
    root = read_root if opname in READ_OPS else write_root
    try:
        print(json.dumps(op(root, req)))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — never crash into the model's face
        fail("file tool error: " + str(e))


if __name__ == "__main__":
    main()
