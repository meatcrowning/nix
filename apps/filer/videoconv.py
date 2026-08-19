"""videoconv — filer's video context-menu actions.

Four of them, sharing one QProcess/toast harness:

  * **"convert to <format>"** — `convert_formats()`/`convert()`, a plain
    transcode to a target the person named (mp4/webm/mkv/gif/mp3). No plan or
    dialog: they picked a format, not a bitrate. Each target is gated on the
    encoder ffmpeg actually has, so the menu never offers one that would fail.


  * **"compress to <10MB" / "compress to <4MB"** — the main job: take a video
    the user right-clicked and produce an mp4 next to it that is comfortably
    under the ceiling an upload form/chat app enforces, as fast as this machine
    can do it, without the user answering any questions about codecs. The
    ceiling is a PARAMETER (`limit`, bytes) threaded through `plan`,
    `out_path_for` and the job — one sizing model, two rows in the menu —
    defaulting to `LIMIT`. Everything below the next paragraph is about this
    one.
  * **"copy without audio"** — `strip_argv()`/`stripAudio()`, at the bottom.
    A stream copy, not an encode: no plan, no dialog, no quality decisions.

Two halves:

  * `plan()` — pure, cheap (one ffprobe) and side-effect free. It decides
    everything: whether the job is even possible, the resolution/fps/bitrate
    ladder rung that fits the budget, which encoder to use, and how long it
    thinks the encode will take. QML calls it BEFORE showing anything, so the
    menu can go straight to work when the answer is "a second or two" and put a
    confirmation in front of the user when it isn't.
  * `VideoConv` — the QObject filer exposes. Runs ffmpeg through QProcess (never
    blocking the UI), turns its `-progress` stream into a desktop toast that
    updates in place, and verifies the result actually fits.

Sizing model. The budget is a *total* bit budget — `target(limit)` bytes spread
over the clip's duration — so everything falls out of one number:

    total_kbps = target(limit) * 8 / duration

Audio takes its slice first (it's the part that sounds broken when starved),
video gets the rest, and the rest picks the resolution: `LADDER` is the minimum
video bitrate each height is worth encoding at, so we simply take the tallest
rung the budget can pay for (never upscaling past the source).

Rate control is CRF-with-a-cap (`-crf N -maxrate V -bufsize 2V`), not plain
average-bitrate. Easy content (a screen recording, a talking head) then comes in
*well* under budget at genuinely good quality instead of being padded up to the
target, while VBV guarantees the hard content can't run over it. Since that
guarantee is bounded by the buffer rather than exact, `run()` re-checks the
finished file and does one corrective pass if it somehow lands over the line.

Encoder choice is "the CPU unless that would be slow": libx264 beats NVENC
badly at these bitrates, and on a 16-thread box it encodes a short clip faster
than the GPU can even initialise. Only when the estimate crosses SLOW_SECONDS
does it hand over to h264_nvenc (when present), which is roughly an order of
magnitude quicker on long/large sources.
"""
import json
import os
import re
import subprocess

from PySide6.QtCore import QObject, QProcess, Signal, Slot

# The toast and the binary resolver used to live in this file; they moved to
# notify.py when FileOps grew failure toasts of its own, so filer has one
# implementation of "how a filer toast is spelled" rather than two.
from notify import tool as _tool, toast as _toast_send

# "Under 10MB" in the sense every uploader means it: 10 million bytes is below
# both the 10MB and the 10MiB reading, so a file that fits this fits either.
LIMIT = 10_000_000
# The tighter ceiling, offered beside it: the same reading of "4MB" imgconv.py
# uses for stills, and under 4chan's 4 MiB webm limit as well.
LIMIT_SMALL = 4_000_000
# Every ceiling the menu offers, largest first — the one list a new row is
# added to, since everything else takes the limit as an argument.
LIMITS = (LIMIT, LIMIT_SMALL)


def target(limit=None):
    """What we actually aim at. The gap absorbs mp4 container overhead and the
    slack VBV allows within one buffer period, so we land under `limit` without
    a retry."""
    return int((LIMIT if limit is None else limit) * 0.93)


def label(limit=None):
    """`10_000_000` -> `"10MB"`, for the menu row, the toasts and the refusals."""
    return "%gMB" % ((LIMIT if limit is None else limit) / 1_000_000.0)


TARGET = target(LIMIT)

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".flv",
              ".mpg", ".mpeg", ".ts", ".m2ts", ".mts", ".ogv", ".3gp", ".vob",
              ".divx", ".asf", ".rm", ".rmvb", ".f4v", ".mxf"}

# (height, minimum video kbps worth spending at that height). Descending — the
# first rung whose price the budget can pay, and that doesn't upscale the
# source, wins. Values are the usual "looks fine for a web upload" floors, not
# broadcast numbers: this is a size-constrained encode, the alternative to a
# soft 480p is a blocky 720p.
LADDER = [(1080, 2000), (900, 1500), (720, 1000), (540, 650),
          (480, 480), (360, 260), (270, 150), (180, 0)]

# Encoder throughput in megapixels/second, used only for the time ESTIMATE (and
# hence the slow-job warning) — deliberately ~2-3x pessimistic against measured
# numbers on `top`, since the estimate exists to decide whether to interrupt the
# user, and an encode finishing sooner than promised is the harmless direction.
# Scaled by core count so the same constants are sane on book (8 cores) too.
X264_MPPS_PER_CORE = 32.0
NVENC_MPPS = 700.0
DECODE_MPPS_PER_CORE = 75.0
ENCODE_FIXED = 0.8          # process start, probe, mux, faststart shuffle
# Above this the menu stops and asks first (see plan()["slow"]).
SLOW_SECONDS = 20.0


def is_video(path):
    return os.path.splitext(str(path))[1].lower() in VIDEO_EXTS


def _fps_of(stream):
    """Frames per second from a stream's r_frame_rate ("30000/1001"). 0 if the
    field is missing or degenerate (some containers report 0/0)."""
    r = stream.get("r_frame_rate") or stream.get("avg_frame_rate") or ""
    m = re.match(r"^(\d+)/(\d+)$", str(r))
    if not m:
        return 0.0
    num, den = int(m.group(1)), int(m.group(2))
    return num / den if den else 0.0


def probe(path):
    """ffprobe the file into {duration, w, h, fps, vcodec, audio, channels} —
    or None if it isn't decodable/has no video stream."""
    try:
        out = subprocess.run(
            [_tool("ffprobe"), "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", "--", str(path)],
            capture_output=True, text=True, timeout=20)
        info = json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    streams = info.get("streams") or []
    vid = next((s for s in streams if s.get("codec_type") == "video"
                # cover art in an mp3/mkv is a "video" stream of one frame
                and s.get("disposition", {}).get("attached_pic", 0) != 1), None)
    if vid is None:
        return None
    aud = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float((info.get("format") or {}).get("duration")
                         or vid.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "duration": duration,
        "w": int(vid.get("width") or 0),
        "h": int(vid.get("height") or 0),
        "fps": _fps_of(vid),
        "vcodec": vid.get("codec_name") or "?",
        "audio": aud is not None,
        "channels": int((aud or {}).get("channels") or 0),
    }


def _have_nvenc():
    """Whether h264_nvenc is both compiled in and has a device to run on.
    Cached — the ffmpeg call costs ~100ms and the answer can't change."""
    if _have_nvenc.cached is None:
        ok = False
        if os.path.exists("/dev/nvidia0"):
            try:
                out = subprocess.run([_tool("ffmpeg"), "-hide_banner", "-encoders"],
                                     capture_output=True, text=True, timeout=10)
                ok = "h264_nvenc" in out.stdout
            except (OSError, subprocess.SubprocessError):
                ok = False
        _have_nvenc.cached = ok
    return _have_nvenc.cached


_have_nvenc.cached = None


# ---- "convert to..." — a plain format transcode, the sibling of the squeeze ----
#
# The compressor above answers "make this fit an upload limit"; this answers
# "give me this clip as a <format>". One recipe per target, chosen for a
# sensible default rather than a knob-farm: the person picked a format, not a
# bitrate. Adding a target is a row here plus (if it needs one) an encoder name
# `_encoders()` can check, so a format ffmpeg cannot actually produce is never
# offered (docs/DESIGN.md 10.4 — no action that silently fails).
#
#   enc:   the video encoder whose presence gates the row (None = stream copy,
#          always available); mp3 gates on its audio encoder instead.
#   audio: the target IS audio, so a source with no audio track is refused with
#          a toast at click time (the stripAudio precedent — no menu-time probe).
CONVERT_FORMATS = [
    {"id": "mp4",  "label": "mp4 (h.264)", "ext": ".mp4",  "enc": "libx264"},
    {"id": "webm", "label": "webm (vp9)",  "ext": ".webm", "enc": "libvpx-vp9"},
    {"id": "mkv",  "label": "mkv (remux)", "ext": ".mkv",  "enc": None},
    {"id": "gif",  "label": "gif",         "ext": ".gif",  "enc": "gif"},
    {"id": "mp3",  "label": "mp3 (audio)", "ext": ".mp3",  "enc": "libmp3lame",
     "audio": True},
]


def _encoders():
    """The set of encoder names this ffmpeg build actually carries, parsed once
    from `ffmpeg -encoders`. Empty if ffmpeg is missing or the probe fails — the
    caller treats that as "can't tell" and offers everything, since a click then
    fails out loud (a toast), never silently."""
    if _encoders.cache is None:
        names = set()
        try:
            out = subprocess.run([_tool("ffmpeg"), "-hide_banner", "-encoders"],
                                 capture_output=True, text=True, timeout=10)
            for line in out.stdout.splitlines():
                m = re.match(r"^\s*[A-Z.]{6}\s+(\S+)", line)
                if m:
                    names.add(m.group(1))
        except (OSError, subprocess.SubprocessError):
            pass
        _encoders.cache = names
    return _encoders.cache


_encoders.cache = None


def convert_formats():
    """The convert-to targets this machine can actually produce, in menu order.
    A stream copy (mkv) is always in; an encoded target only when its encoder is
    present — or, if the probe came back empty (ffmpeg unusable/unknown), all of
    them, because the failure then reaches the user as a toast."""
    enc = _encoders()
    return [{"id": f["id"], "label": f["label"]}
            for f in CONVERT_FORMATS
            if f["enc"] is None or not enc or f["enc"] in enc]


def convert_out_path(src, fmt):
    """`clip.mkv` -> `clip.mp4`, next to the source, never clobbering. When the
    target extension equals the source's (`clip.mp4` -> mp4) the stem is tagged
    `-conv` so the encode never reads and writes the same file."""
    spec = next(f for f in CONVERT_FORMATS if f["id"] == fmt)
    stem, srcext = os.path.splitext(str(src))
    ext = spec["ext"]
    base = stem if srcext.lower() != ext else stem + "-conv"
    cand = base + ext
    n = 2
    while os.path.lexists(cand):
        cand = "%s-%d%s" % (base, n, ext)
        n += 1
    return cand


def convert_argv(src, dst, fmt):
    """The ffmpeg command for a convert-to target. `-progress pipe:1` drives the
    same toast the compressor uses; `-map 0:a:0?` keeps audio when there is any
    and does not fail when there isn't (the `?` makes the stream optional)."""
    a = [_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
         "-progress", "pipe:1", "-nostats", "-i", src]
    if fmt == "mp4":
        a += ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264",
              "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-f", "mp4"]
    elif fmt == "webm":
        a += ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libvpx-vp9",
              "-crf", "32", "-b:v", "0", "-row-mt", "1", "-pix_fmt", "yuv420p",
              "-c:a", "libopus", "-b:a", "128k", "-f", "webm"]
    elif fmt == "mkv":
        # Remux: every stream copied bit-for-bit into matroska, which holds
        # essentially anything, so this is fast and lossless.
        a += ["-map", "0", "-c", "copy", "-f", "matroska"]
    elif fmt == "gif":
        # Two-pass palette so the gif isn't a 216-colour mess; 12fps/480px is the
        # usual "shareable clip" size rather than a faithful copy.
        a += ["-vf", "fps=12,scale=480:-2:flags=lanczos,split[a][b];"
                     "[a]palettegen[p];[b][p]paletteuse", "-loop", "0", "-f", "gif"]
    elif fmt == "mp3":
        a += ["-vn", "-map", "0:a:0", "-c:a", "libmp3lame", "-q:a", "2", "-f", "mp3"]
    return a + [dst]


def _fmt_dur(sec):
    sec = int(round(sec))
    if sec < 60:
        return "%ds" % sec
    if sec < 3600:
        return "%dm %02ds" % (sec // 60, sec % 60)
    return "%dh %02dm" % (sec // 3600, (sec % 3600) // 60)


def _human(b):
    b = float(b)
    for u in ("B", "K", "M", "G"):
        if b < 1024 or u == "G":
            return "%dB" % b if u == "B" else "%.1f%s" % (b, u)
        b /= 1024


def out_path_for(src, limit=None):
    """`clip.mkv` -> `clip-10mb.mp4`, next to the source, never clobbering an
    existing file (`-10mb-2.mp4`, …). The tag is the ceiling, so a clip squeezed
    both ways ends up as `clip-10mb.mp4` and `clip-4mb.mp4` rather than one
    overwriting the other."""
    tag = label(limit).lower()
    stem = os.path.splitext(str(src))[0]
    cand = "%s-%s.mp4" % (stem, tag)
    n = 2
    while os.path.lexists(cand):
        cand = "%s-%s-%d.mp4" % (stem, tag, n)
        n += 1
    return cand


def mute_path_for(src):
    """`clip.mkv` -> `clip-muted.mkv`, next to the source, never clobbering an
    existing file. Keeps the source's EXTENSION, unlike the compressor's: this
    is a stream copy, so the container stays exactly what it was."""
    stem, ext = os.path.splitext(str(src))
    cand = stem + "-muted" + ext
    n = 2
    while os.path.lexists(cand):
        cand = "%s-muted-%d%s" % (stem, n, ext)
        n += 1
    return cand


def strip_argv(src, dst, video_only=False):
    """The ffmpeg command for "copy without audio". Everything but the audio is
    copied bit-for-bit — no re-encode, so it runs at IO speed and the video is
    the same video, not a generation-loss copy of it.

    `-map 0 -map -0:a` takes every stream and then subtracts the audio ones, so
    subtitles and mkv attachments survive; `-dn` drops data streams, which are
    the usual reason a copy into mp4 refuses. `video_only` is the retry for a
    container/codec combination that still won't take (see `_on_done`)."""
    argv = [_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-progress", "pipe:1", "-nostats", "-i", src]
    argv += ["-map", "0:v"] if video_only else ["-map", "0", "-map", "-0:a"]
    argv += ["-c", "copy", "-dn"]
    if os.path.splitext(dst)[1].lower() in (".mp4", ".m4v", ".mov"):
        argv += ["-movflags", "+faststart"]
    return argv + [dst]


def plan(path, size=None, limit=None):
    """Decide how (and whether) to squeeze `path` under `limit` (default LIMIT).

    Returns a plain dict, safe to hand straight to QML:
      ok         — False means don't start; `reason` says why, in user words
      slow       — the estimate crossed SLOW_SECONDS: confirm before starting
      estSec     — estimated encode seconds
      summary    — one line describing the output ("720p30 h264 (cpu), 1.4Mb/s")
      warning    — the confirm-dialog body (only meaningful when slow)
      plus the encoder settings run() needs: height/fps/vKbps/aKbps/channels/…
    """
    path = str(path)
    limit = LIMIT if limit is None else int(limit)
    budget, cap = target(limit), label(limit)
    try:
        size = os.path.getsize(path) if size is None else int(size)
    except OSError:
        return {"ok": False, "reason": "can't read that file"}
    if not is_video(path):
        return {"ok": False, "reason": "not a video file"}
    if size <= limit:
        return {"ok": False, "reason": "already under %s (%s)" % (cap, _human(size))}

    info = probe(path)
    if info is None:
        return {"ok": False, "reason": "no video stream ffmpeg can read"}
    dur, src_h, src_w = info["duration"], info["h"], info["w"]
    if dur <= 0 or src_h <= 0 or src_w <= 0:
        return {"ok": False, "reason": "unknown duration - can't budget a bitrate"}

    total_kbps = budget * 8 / 1000.0 / dur
    if total_kbps < 40:
        # ~35 minutes per 10MB is where even 180p stops being video — spending
        # minutes of encoding to produce a slideshow helps nobody. The line
        # scales with the ceiling, so 4MB gives up ~14 minutes in.
        return {"ok": False, "reason": "%s is too long to fit %s - trim it first"
                                       % (_fmt_dur(dur), cap)}

    # Audio first — starved audio is more obviously broken than soft video —
    # but never more than a third of the budget on a long clip.
    if not info["audio"]:
        a_kbps, channels = 0, 0
    else:
        a_kbps = 128 if total_kbps > 900 else 96 if total_kbps > 500 else \
                 64 if total_kbps > 260 else 48
        a_kbps = int(min(a_kbps, max(32, total_kbps * 0.35)))
        channels = 2 if (a_kbps >= 96 and info["channels"] >= 2) else 1

    v_kbps = int(total_kbps - a_kbps)
    height = next(h for h, floor in LADDER if h <= src_h and v_kbps >= floor) \
        if any(h <= src_h and v_kbps >= floor for h, floor in LADDER) else \
        min(src_h, LADDER[-1][0])
    height -= height % 2                       # h264 needs even dimensions

    src_fps = info["fps"] or 30.0
    fps = min(src_fps, 30.0)                   # nothing being uploaded needs 60
    if v_kbps < 300:
        fps = min(fps, 24.0)                   # spend the bits on pixels instead

    scale = height / float(src_h)
    out_mpx = (src_w * scale) * height / 1e6 * fps * dur
    src_mpx = src_w * src_h / 1e6 * src_fps * dur
    cores = max(1, os.cpu_count() or 4)
    decode = src_mpx / (DECODE_MPPS_PER_CORE * cores)
    est_x264 = out_mpx / (X264_MPPS_PER_CORE * cores) + decode + ENCODE_FIXED

    # CPU unless that would be slow: x264 is much better at these bitrates, and
    # on a short clip it beats NVENC outright once GPU init is counted.
    if est_x264 > SLOW_SECONDS and _have_nvenc():
        encoder, est = "h264_nvenc", out_mpx / NVENC_MPPS + decode + ENCODE_FIXED
    else:
        encoder, est = "libx264", est_x264

    summary = "%dp%d %s, %s" % (
        height, round(fps), "gpu" if encoder != "libx264" else "cpu",
        ("%.1fMb/s" % (v_kbps / 1000.0)) if v_kbps >= 1000 else "%dkb/s" % v_kbps)

    # Two things are worth stopping the user for: a job that won't be over
    # before they've forgotten they started it, and a budget so tight the result
    # will look bad. Everything else just runs.
    slow, rough = est > SLOW_SECONDS, v_kbps < 260
    lines = ["compress to under %s?" % cap,
             "%s -> %s" % (_human(size), _human(budget)), summary]
    if rough:
        lines.append("at this length that will look rough")
    if slow:
        lines.append("this will take around " + _fmt_dur(est))
    return {
        "ok": True,
        "reason": "",
        "slow": slow,
        "rough": rough,
        "ask": slow or rough,
        "estSec": round(est, 1),
        "estStr": _fmt_dur(est),
        "summary": summary,
        "warning": "\n".join(lines),
        "height": height, "fps": round(fps, 3), "vKbps": v_kbps,
        "aKbps": a_kbps, "channels": channels, "encoder": encoder,
        "durationSec": dur, "srcHeight": src_h,
        "limit": limit, "cap": cap, "outPath": out_path_for(path, limit),
    }


def build_argv(src, dst, p, crf_bump=0, rate_scale=1.0):
    """The ffmpeg command for a plan. `-progress pipe:1` is what drives the
    toast; `crf_bump`/`rate_scale` are the corrective second pass."""
    v = max(48, int(p["vKbps"] * rate_scale))
    vf = []
    if p["height"] < p["srcHeight"]:
        vf.append("scale=-2:%d:flags=bicubic" % p["height"])
    vf.append("fps=%s" % p["fps"])

    argv = [_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-progress", "pipe:1", "-nostats", "-i", src, "-map", "0:v:0"]
    if p["aKbps"]:
        argv += ["-map", "0:a:0"]
    argv += ["-sn", "-dn", "-vf", ",".join(vf), "-pix_fmt", "yuv420p"]
    if p["encoder"] == "libx264":
        # CRF with a hard VBV cap: quality-driven where the content is cheap,
        # bitrate-capped where it isn't. Never plain -b:v, which would inflate
        # an easy clip to the full budget for nothing.
        argv += ["-c:v", "libx264", "-preset", "faster", "-profile:v", "high",
                 "-crf", str(23 + crf_bump),
                 "-maxrate", "%dk" % v, "-bufsize", "%dk" % (v * 2)]
    else:
        argv += ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
                 "-profile:v", "high", "-rc", "vbr", "-cq", str(26 + crf_bump),
                 "-b:v", "0", "-maxrate", "%dk" % v, "-bufsize", "%dk" % (v * 2)]
    if p["aKbps"]:
        argv += ["-c:a", "aac", "-b:a", "%dk" % p["aKbps"], "-ac", str(p["channels"])]
    argv += ["-movflags", "+faststart", "-f", "mp4", dst]
    return argv


class VideoConv(QObject):
    """Bridge for the video rows of the context menu.

    `plan(path)` is synchronous (one ffprobe) and returns the dict above so QML
    can decide between "just do it" and "ask first". `start(path)` runs the
    encode asynchronously and reports entirely through desktop toasts — a live
    one that updates in place while encoding, then a completion/failure toast —
    the same notify-send --replace-id trick surfer's downloads use, so filer's
    progress looks like every other toast on this desktop. `stripAudio(path)` is
    the second action and rides the same plumbing; only `_on_done` differs.
    """

    finished = Signal(str)   # output path ("" on failure) — QML reselects it

    def __init__(self, parent=None):
        super().__init__(parent)
        # key ("<kind>:<src>") -> job dict; also the "already running" set. The
        # kind is in the key so stripping one file's audio doesn't look like a
        # compression of it already being in flight.
        self._jobs = {}

    # ---- toasts ----
    def _toast(self, job, title, body, value=None, urgency=None, persist=False):
        # notify.toast does the sending (see its docstring for why an ongoing
        # job's toast is -t 0); this only keeps the job's notification id, so
        # every update of one encode morphs the toast already on screen.
        nid = _toast_send(title, body, urgency=urgency, replace_id=job.get("nid"),
                          value=value, persist=persist)
        if nid is not None:
            job["nid"] = nid

    @staticmethod
    def _bar(pct, width=16):
        fill = int(round(pct / 100.0 * width))
        return "█" * fill + "░" * (width - fill)

    @Slot(str, result=bool)
    def isVideo(self, path):
        return is_video(path)

    @Slot(str, result=bool)
    def isBusy(self, path):
        return any(j["src"] == str(path) for j in self._jobs.values())

    # Both are offered with and without an explicit ceiling: QML names one
    # (10MB / 4MB), while anything older calling plan(path)/start(path) still
    # gets LIMIT. Stacked @Slot decorators register both arities.
    @Slot(str, result="QVariant")
    @Slot(str, int, result="QVariant")
    def plan(self, path, limit=None):
        p = plan(str(path), limit=limit)
        if p.get("ok") and "compress:" + str(path) in self._jobs:
            return {"ok": False, "reason": "already compressing that file"}
        return p

    @Slot(str)
    @Slot(str, int)
    def start(self, path, limit=None):
        """Begin (or refuse) a conversion. Safe to call straight from the menu:
        it re-plans, so nothing depends on the QML side having done so."""
        src = str(path)
        # One compression per source, whichever ceiling: the second would be
        # the same decode again, for a file the first is about to produce a
        # smaller version of anyway.
        if "compress:" + src in self._jobs:
            return
        p = plan(src, limit=limit)
        if not p.get("ok"):
            self._toast({}, "can't compress", p.get("reason", "?"), urgency="normal")
            return
        job = {"kind": "compress", "verb": "compressing", "key": "compress:" + src,
               "src": src, "dst": p["outPath"], "plan": p, "pct": -1,
               "attempt": 1, "nid": None, "err": ""}
        self._jobs[job["key"]] = job
        self._toast(job, "compressing " + os.path.basename(src),
                    "%s\n%s ~%s" % (self._bar(0), p["summary"], p["estStr"]), 0,
                    persist=True)
        self._spawn(job, build_argv(src, job["dst"], p))

    @Slot(result="QVariant")
    def convertFormats(self):
        """The convert-to targets the menu should offer on THIS machine — built
        as the submenu opens, like Phone.devices(), so it reflects what ffmpeg
        can actually do here rather than a list frozen at startup."""
        return convert_formats()

    @Slot(str, str)
    def convert(self, path, fmt):
        """"convert to <format>": a plain transcode beside the source. Like
        stripAudio it is direct (no plan/dialog) and reports through the same
        toast; a refusal (not a video, unreadable, mp3 of a silent clip, already
        running) comes back as a toast rather than a silent no-op."""
        src = str(path)
        spec = next((f for f in CONVERT_FORMATS if f["id"] == fmt), None)
        if spec is None:
            return
        key = "convert-%s:%s" % (fmt, src)
        if key in self._jobs:
            return
        if not is_video(src):
            self._toast({}, "can't convert", "not a video file", urgency="normal")
            return
        info = probe(src)
        if info is None:
            self._toast({}, "can't convert", "no video stream ffmpeg can read",
                        urgency="normal")
            return
        if spec.get("audio") and not info["audio"]:
            self._toast({}, "can't convert",
                        "%s has no audio track" % os.path.basename(src),
                        urgency="normal")
            return
        dst = convert_out_path(src, fmt)
        job = {"kind": "convert", "verb": "converting", "key": key,
               "src": src, "dst": dst, "pct": -1, "attempt": 1,
               "nid": None, "err": "",
               "plan": {"durationSec": info["duration"],
                        "summary": "to " + spec["label"]}}
        self._jobs[key] = job
        self._toast(job, "converting " + os.path.basename(src),
                    "%s\nto %s" % (self._bar(0), spec["label"]), 0, persist=True)
        self._spawn(job, convert_argv(src, dst, fmt))

    @Slot(str)
    def stripAudio(self, path):
        """"copy without audio": the same video, minus its soundtrack, beside
        it. A stream copy — there is nothing to decide and nothing to warn
        about, so unlike `start()` this has no `plan()` half and the menu calls
        it directly. Refusals (not a video, no audio in it, already running)
        come back as a toast, the way a failed compression does."""
        src = str(path)
        key = "mute:" + src
        if key in self._jobs:
            return
        if not is_video(src):
            self._toast({}, "can't strip audio", "not a video file", urgency="normal")
            return
        info = probe(src)
        if info is None:
            self._toast({}, "can't strip audio", "no video stream ffmpeg can read",
                        urgency="normal")
            return
        if not info["audio"]:
            # Nothing to do, and a silent "-muted" duplicate would be a
            # confusing thing to find in the directory.
            self._toast({}, "can't strip audio",
                        "%s has no audio track" % os.path.basename(src),
                        urgency="normal")
            return
        job = {"kind": "mute", "verb": "stripping audio from", "key": key,
               "src": src, "dst": mute_path_for(src), "pct": -1, "attempt": 1,
               "nid": None, "err": "",
               "plan": {"durationSec": info["duration"], "summary": "stream copy"}}
        self._jobs[key] = job
        self._toast(job, "stripping audio from " + os.path.basename(src),
                    "%s\nstream copy" % self._bar(0), 0, persist=True)
        self._spawn(job, strip_argv(src, job["dst"]))

    def _spawn(self, job, argv):
        proc = QProcess(self)
        job["proc"] = proc
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.readyReadStandardOutput.connect(lambda: self._on_progress(job))
        proc.readyReadStandardError.connect(lambda: self._on_stderr(job))
        proc.finished.connect(lambda code, status: self._on_done(job, code))
        proc.errorOccurred.connect(lambda _e: self._on_error(job))
        proc.start(argv[0], argv[1:])

    # ---- ffmpeg plumbing ----
    def _on_progress(self, job):
        """ffmpeg's -progress stream is `key=value` lines; out_time_us against
        the known duration gives the percentage. Toast only on whole-percent
        steps, so a long encode doesn't spam the notification server."""
        try:
            text = bytes(job["proc"].readAllStandardOutput()).decode("utf-8", "replace")
        except (RuntimeError, UnicodeError):
            return
        us = None
        for line in text.splitlines():
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                val = line.split("=", 1)[1].strip()
                if val.isdigit():
                    # out_time_ms is misnamed upstream: it is microseconds too.
                    us = int(val)
        if us is None:
            return
        dur = job["plan"]["durationSec"]
        pct = max(0, min(99, int(us / 1e6 * 100 / dur))) if dur > 0 else 0
        if pct == job["pct"]:
            return
        job["pct"] = pct
        pass_note = "" if job["attempt"] == 1 else "  (pass %d)" % job["attempt"]
        self._toast(job, job["verb"] + " " + os.path.basename(job["src"]),
                    "%s %d%%\n%s%s" % (self._bar(pct), pct,
                                       job["plan"]["summary"], pass_note), pct,
                    persist=True)

    def _on_stderr(self, job):
        try:
            text = bytes(job["proc"].readAllStandardError()).decode("utf-8", "replace")
        except (RuntimeError, UnicodeError):
            return
        for line in text.splitlines():
            if line.strip():
                job["err"] = line.strip()   # keep the last real line for the toast

    def _on_error(self, job):
        if job["key"] in self._jobs:
            self._fail(job, job["err"] or "ffmpeg could not be started")

    def _on_done(self, job, code):
        if job["key"] not in self._jobs:      # already finished/failed
            return
        dst = job["dst"]
        if job["kind"] == "convert":
            if code == 0 and os.path.exists(dst):
                self._toast(job, "converted: " + os.path.basename(dst),
                            "%s\n%s" % (_human(os.path.getsize(dst)),
                                        job["plan"]["summary"]), 100)
                self._cleanup(job)
                self.finished.emit(dst)
                return
            self._fail(job, job["err"] or "ffmpeg exited %d" % code)
            return
        if job["kind"] == "mute":
            if code == 0 and os.path.exists(dst):
                self._toast(job, "audio stripped: " + os.path.basename(dst),
                            "%s\ncopied without the soundtrack" % _human(os.path.getsize(dst)),
                            100)
                self._cleanup(job)
                self.finished.emit(dst)
                return
            if job["attempt"] == 1:
                # A container that won't take one of the copied subtitle/
                # attachment streams. Retry with the video alone, which every
                # container this menu offers can hold.
                job["attempt"], job["pct"] = 2, -1
                self._restart(job, strip_argv(job["src"], dst, video_only=True))
                return
            self._fail(job, job["err"] or "ffmpeg exited %d" % code)
            return
        if code != 0 or not os.path.exists(dst):
            self._fail(job, job["err"] or "ffmpeg exited %d" % code)
            return
        size = os.path.getsize(dst)
        limit = job["plan"].get("limit", LIMIT)
        if size > limit and job["attempt"] == 1:
            # VBV slack (or a pathological source) put us over. One corrective
            # pass, scaled by how far off we were, with a slightly higher CRF so
            # the cap is actually reachable instead of being fought by quality.
            job["attempt"] = 2
            job["pct"] = -1
            scale = max(0.35, target(limit) / float(size) * 0.95)
            try:
                os.unlink(dst)
            except OSError:
                pass
            self._toast(job, "compressing " + os.path.basename(job["src"]),
                        "%s\n%s  (pass 2 - overshot)" % (self._bar(0), job["plan"]["summary"]), 0,
                        persist=True)
            self._restart(job, build_argv(job["src"], dst, job["plan"],
                                          crf_bump=3, rate_scale=scale))
            return
        self._toast(job, "compressed " + os.path.basename(dst),
                    "%s -> %s\n%s" % (_human(os.path.getsize(job["src"])),
                                      _human(size), job["plan"]["summary"]), 100)
        self._cleanup(job)
        self.finished.emit(dst)

    def _restart(self, job, argv):
        """Second pass of a job whose first one is finishing right now. The
        deleteLater is deferred on purpose: we are inside that QProcess's own
        finished() handler."""
        if job.get("proc") is not None:
            job["proc"].deleteLater()
        self._spawn(job, argv)

    def _fail(self, job, msg):
        try:
            if os.path.exists(job["dst"]):
                os.unlink(job["dst"])       # never leave a truncated file behind
        except OSError:
            pass
        verb = {"mute": "strip failed", "convert": "convert failed"}.get(
            job.get("kind"), "compress failed")
        self._toast(job, verb + ": " + os.path.basename(job["src"]),
                    msg[:200], urgency="critical")
        self._cleanup(job)
        self.finished.emit("")

    def _cleanup(self, job):
        self._jobs.pop(job["key"], None)
        proc = job.get("proc")
        if proc is not None:
            proc.deleteLater()
