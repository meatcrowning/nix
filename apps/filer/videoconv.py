"""videoconv — filer's "compress to <10MB" context-menu action.

One job: take a video the user right-clicked and produce an mp4 next to it that
is comfortably under the 10MB ceiling every upload form/chat app enforces, as
fast as this machine can do it, without the user answering any questions about
codecs.

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

Sizing model. The budget is a *total* bit budget — TARGET bytes spread over the
clip's duration — so everything falls out of one number:

    total_kbps = TARGET * 8 / duration

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
import shutil
import subprocess

from PySide6.QtCore import QObject, QProcess, Signal, Slot

# "Under 10MB" in the sense every uploader means it: 10 million bytes is below
# both the 10MB and the 10MiB reading, so a file that fits this fits either.
LIMIT = 10_000_000
# What we actually aim at. The gap absorbs mp4 container overhead and the slack
# VBV allows within one buffer period, so we land under LIMIT without a retry.
TARGET = int(LIMIT * 0.93)

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


def _tool(name):
    """Absolute path to an ffmpeg-family binary. filer can be launched from a
    .desktop entry or the Quickshell runner, whose PATH need not carry the nix
    profile dirs — resolve against them explicitly rather than trusting PATH."""
    found = shutil.which(name)
    if found:
        return found
    user = os.environ.get("USER", "")
    for d in (os.path.expanduser("~/.nix-profile/bin"),
              "/etc/profiles/per-user/%s/bin" % user,
              "/run/current-system/sw/bin", "/usr/bin"):
        cand = os.path.join(d, name)
        if os.path.exists(cand):
            return cand
    return name


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


def out_path_for(src):
    """`clip.mkv` -> `clip-10mb.mp4`, next to the source, never clobbering an
    existing file (`-10mb-2.mp4`, …)."""
    stem = os.path.splitext(str(src))[0]
    cand = stem + "-10mb.mp4"
    n = 2
    while os.path.lexists(cand):
        cand = "%s-10mb-%d.mp4" % (stem, n)
        n += 1
    return cand


def plan(path, size=None):
    """Decide how (and whether) to squeeze `path` under LIMIT.

    Returns a plain dict, safe to hand straight to QML:
      ok         — False means don't start; `reason` says why, in user words
      slow       — the estimate crossed SLOW_SECONDS: confirm before starting
      estSec     — estimated encode seconds
      summary    — one line describing the output ("720p30 h264 (cpu), 1.4Mb/s")
      warning    — the confirm-dialog body (only meaningful when slow)
      plus the encoder settings run() needs: height/fps/vKbps/aKbps/channels/…
    """
    path = str(path)
    try:
        size = os.path.getsize(path) if size is None else int(size)
    except OSError:
        return {"ok": False, "reason": "can't read that file"}
    if not is_video(path):
        return {"ok": False, "reason": "not a video file"}
    if size <= LIMIT:
        return {"ok": False, "reason": "already under 10MB (%s)" % _human(size)}

    info = probe(path)
    if info is None:
        return {"ok": False, "reason": "no video stream ffmpeg can read"}
    dur, src_h, src_w = info["duration"], info["h"], info["w"]
    if dur <= 0 or src_h <= 0 or src_w <= 0:
        return {"ok": False, "reason": "unknown duration - can't budget a bitrate"}

    total_kbps = TARGET * 8 / 1000.0 / dur
    if total_kbps < 40:
        # ~35 minutes per 10MB is where even 180p stops being video — spending
        # minutes of encoding to produce a slideshow helps nobody.
        return {"ok": False, "reason": "%s is too long to fit 10MB - trim it first"
                                       % _fmt_dur(dur)}

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
    lines = ["compress to under 10MB?", "%s -> %s" % (_human(size), _human(TARGET)),
             summary]
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
        "durationSec": dur, "srcHeight": src_h, "outPath": out_path_for(path),
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
    """Bridge for the context menu's "compress to <10MB".

    `plan(path)` is synchronous (one ffprobe) and returns the dict above so QML
    can decide between "just do it" and "ask first". `start(path)` runs the
    encode asynchronously and reports entirely through desktop toasts — a live
    one that updates in place while encoding, then a completion/failure toast —
    the same notify-send --replace-id trick surfer's downloads use, so filer's
    progress looks like every other toast on this desktop.
    """

    finished = Signal(str)   # output path ("" on failure) — QML reselects it

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs = {}     # src path -> job dict (also the "already running" set)

    # ---- toasts ----
    def _toast(self, job, title, body, value=None, urgency=None):
        args = [_tool("notify-send"), "-a", "filer", "-p"]
        if job.get("nid"):
            args += ["-r", str(job["nid"])]
        if value is not None:
            args += ["-h", "int:value:%d" % int(value)]
        if urgency:
            args += ["-u", urgency]
        args += [title, body]
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=2)
            nid = out.stdout.strip()
            if nid.isdigit():
                job["nid"] = int(nid)
        except (OSError, subprocess.SubprocessError):
            pass

    @staticmethod
    def _bar(pct, width=16):
        fill = int(round(pct / 100.0 * width))
        return "█" * fill + "░" * (width - fill)

    @Slot(str, result=bool)
    def isVideo(self, path):
        return is_video(path)

    @Slot(str, result=bool)
    def isBusy(self, path):
        return str(path) in self._jobs

    @Slot(str, result="QVariant")
    def plan(self, path):
        p = plan(str(path))
        if p.get("ok") and str(path) in self._jobs:
            return {"ok": False, "reason": "already compressing that file"}
        return p

    @Slot(str)
    def start(self, path):
        """Begin (or refuse) a conversion. Safe to call straight from the menu:
        it re-plans, so nothing depends on the QML side having done so."""
        src = str(path)
        if src in self._jobs:
            return
        p = plan(src)
        if not p.get("ok"):
            self._toast({}, "can't compress", p.get("reason", "?"), urgency="normal")
            return
        job = {"src": src, "dst": p["outPath"], "plan": p, "pct": -1,
               "attempt": 1, "nid": None, "err": ""}
        self._jobs[src] = job
        self._toast(job, "compressing " + os.path.basename(src),
                    "%s\n%s ~%s" % (self._bar(0), p["summary"], p["estStr"]), 0)
        self._spawn(job, build_argv(src, job["dst"], p))

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
        self._toast(job, "compressing " + os.path.basename(job["src"]),
                    "%s %d%%\n%s%s" % (self._bar(pct), pct,
                                       job["plan"]["summary"], pass_note), pct)

    def _on_stderr(self, job):
        try:
            text = bytes(job["proc"].readAllStandardError()).decode("utf-8", "replace")
        except (RuntimeError, UnicodeError):
            return
        for line in text.splitlines():
            if line.strip():
                job["err"] = line.strip()   # keep the last real line for the toast

    def _on_error(self, job):
        if job["src"] in self._jobs:
            self._fail(job, job["err"] or "ffmpeg could not be started")

    def _on_done(self, job, code):
        if job["src"] not in self._jobs:      # already finished/failed
            return
        dst = job["dst"]
        if code != 0 or not os.path.exists(dst):
            self._fail(job, job["err"] or "ffmpeg exited %d" % code)
            return
        size = os.path.getsize(dst)
        if size > LIMIT and job["attempt"] == 1:
            # VBV slack (or a pathological source) put us over. One corrective
            # pass, scaled by how far off we were, with a slightly higher CRF so
            # the cap is actually reachable instead of being fought by quality.
            job["attempt"] = 2
            job["pct"] = -1
            scale = max(0.35, TARGET / float(size) * 0.95)
            try:
                os.unlink(dst)
            except OSError:
                pass
            self._toast(job, "compressing " + os.path.basename(job["src"]),
                        "%s\n%s  (pass 2 - overshot)" % (self._bar(0), job["plan"]["summary"]), 0)
            if job.get("proc") is not None:
                job["proc"].deleteLater()   # deferred: we're inside its finished()
            self._spawn(job, build_argv(job["src"], dst, job["plan"],
                                        crf_bump=3, rate_scale=scale))
            return
        self._toast(job, "compressed " + os.path.basename(dst),
                    "%s -> %s\n%s" % (_human(os.path.getsize(job["src"])),
                                      _human(size), job["plan"]["summary"]), 100)
        self._cleanup(job)
        self.finished.emit(dst)

    def _fail(self, job, msg):
        try:
            if os.path.exists(job["dst"]):
                os.unlink(job["dst"])       # never leave a truncated mp4 behind
        except OSError:
            pass
        self._toast(job, "compress failed: " + os.path.basename(job["src"]),
                    msg[:200], urgency="critical")
        self._cleanup(job)
        self.finished.emit("")

    def _cleanup(self, job):
        self._jobs.pop(job["src"], None)
        proc = job.get("proc")
        if proc is not None:
            proc.deleteLater()
