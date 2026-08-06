#!/usr/bin/env python3
"""Harness for the context menu's "copy without audio" (`videoconv.stripAudio`).

Runs headless with no window and no desktop toast: `_toast_send` is stubbed, so
the run cannot post a notification into the user's session, and every clip it
touches is generated here with ffmpeg. Covers the naming rule, the refusals, a
real strip in two containers (mp4 and mkv, i.e. faststart on and off), that the
video is COPIED rather than re-encoded, and that the compress and strip jobs no
longer collide in the job table.

    nix develop path:~/nix/apps/filer --command python3 tools/strip-audio-test.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "pylib"))

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

import videoconv  # noqa: E402
from notify import tool  # noqa: E402

FAILURES = []
TOASTS = []


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        FAILURES.append(what)


def make_clip(path, audio=True, dur=3):
    argv = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=%d" % dur]
    if audio:
        argv += ["-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % dur]
    argv += ["-c:v", "libx264"]
    if audio:
        argv += ["-c:a", "aac", "-shortest"]
    subprocess.run(argv + [path], check=True)


def video_md5(path):
    """Hash of the VIDEO bitstream only — proves the copy re-encoded nothing."""
    out = subprocess.run([tool("ffmpeg"), "-v", "error", "-i", path,
                          "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def main():
    app = QCoreApplication(sys.argv)
    videoconv._toast_send = lambda title, body, **kw: (TOASTS.append((title, body)), 1)[1]
    tmp = tempfile.mkdtemp(prefix="filer-strip-test-")
    conv = videoconv.VideoConv()

    print("naming")
    check(os.path.basename(videoconv.mute_path_for("/x/clip.mkv")) == "clip-muted.mkv",
          "keeps the source container: clip.mkv -> clip-muted.mkv")
    taken = os.path.join(tmp, "taken.mp4")
    open(taken, "w").close()
    open(os.path.join(tmp, "taken-muted.mp4"), "w").close()
    check(os.path.basename(videoconv.mute_path_for(taken)) == "taken-muted-2.mp4",
          "never clobbers an existing -muted file")

    print("refusals (toast, no output file)")
    notes = os.path.join(tmp, "notes.txt")
    open(notes, "w").close()
    conv.stripAudio(notes)
    check(TOASTS and "not a video" in TOASTS[-1][1], "a non-video is refused")
    silent = os.path.join(tmp, "silent.mp4")
    make_clip(silent, audio=False)
    conv.stripAudio(silent)
    check(TOASTS and "no audio track" in TOASTS[-1][1], "a silent video is refused")
    check(not os.path.exists(os.path.join(tmp, "silent-muted.mp4")),
          "and leaves no -muted duplicate behind")

    print("the strip itself")
    for name in ("clip.mp4", "clip.mkv"):
        src = os.path.join(tmp, name)
        make_clip(src)
        before = videoconv.probe(src)
        check(before["audio"], name + ": source has audio")
        dst = os.path.join(tmp, name.replace(".", "-muted."))
        done = []
        conv.finished.connect(lambda p, d=done: d.append(p))
        conv.stripAudio(src)
        check(conv.isBusy(src), name + ": reports busy while running")
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(app.quit)
        deadline.start(30000)
        while not done:
            app.processEvents()
            if not deadline.isActive():
                break
        check(done and done[0] == dst, name + ": finished() carries the output path")
        after = videoconv.probe(dst) or {}
        check(after.get("audio") is False, name + ": output has no audio stream")
        check((after.get("w"), after.get("h")) == (before["w"], before["h"]),
              name + ": same resolution")
        check(abs(after.get("duration", 0) - before["duration"]) < 0.15,
              name + ": same duration")
        check(video_md5(dst) == video_md5(src),
              name + ": video bitstream is byte-identical (a copy, not an encode)")
        check(not conv.isBusy(src), name + ": job table is empty again")

    print("the two jobs don't collide")
    src = os.path.join(tmp, "clip.mp4")
    conv._jobs["compress:" + src] = {"src": src}
    n = len(TOASTS)
    conv.start(src)
    check(len(conv._jobs) == 1 and len(TOASTS) == n,
          "a running compression blocks a second compression (silently)")
    check(conv.isBusy(src), "isBusy sees a job of either kind")
    conv.stripAudio(src)
    check("mute:" + src in conv._jobs, "but does NOT block a strip of the same file")
    for j in list(conv._jobs.values()):
        if j.get("proc") is not None:
            j["proc"].kill()
            j["proc"].waitForFinished(5000)

    subprocess.run(["rm", "-rf", tmp])
    print("\n%d failed" % len(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
