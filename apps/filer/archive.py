"""archive — filer's "compress to <format>" context-menu action.

The videoconv/imgconv pair squeeze one file to fit an upload limit; this is the
other reading of "compress": pack the selection into an archive (zip, tar.gz,
tar.xz, 7z) next to it. It shells out exactly the way videoconv does — through
`notify.tool` for the binary and `notify.toast` for the one desktop toast filer
speaks — so there is no second idea of "how a filer job is reported".

Two rules carry over from the video side and matter here too:

  * **Never offer a format that would silently fail** (docs/DESIGN.md 10.4).
    `formats()` is built as the submenu opens and lists only the formats whose
    tool actually resolves on THIS machine — `zip`/`7z` are not everywhere, and
    a greyed-out "the tool isn't here" is more honest than a click that dies.
  * **The outcome is always visible.** A finished archive toasts its size, a
    failure toasts the tool's own last stderr line; nothing is silent.

An archive has no cheap progress percentage the way an ffmpeg encode does, so
the working toast is a plain persistent "archiving..." that morphs into the
result — same shape, one fewer number.
"""
import os
import shutil

from PySide6.QtCore import QObject, QProcess, Signal, Slot

from notify import tool as _tool, toast as _toast_send

# Each format: the archiver argv (built from the resolved tool, the absolute
# output path and the relative member names, run with cwd = the shared parent
# so the archive holds bare names, not absolute paths), and the tool(s) whose
# presence gates the row. tar drives gzip/xz itself; 7z ships under a few names
# across distros, so the first that resolves wins.
_SEVENZIP = ("7z", "7zz", "7za")


def _seven_bin():
    for name in _SEVENZIP:
        if shutil.which(name) or _resolved(name):
            return _tool(name)
    return None


def _resolved(name):
    """Whether notify.tool would find `name` somewhere real (not just echo it
    back). tool() returns the name unchanged when nothing is found, so a result
    that is an absolute existing path means it resolved."""
    p = _tool(name)
    return os.path.isabs(p) and os.path.exists(p)


# id -> (extension, [tools that must ALL resolve], argv builder). The builder
# takes (dst, names) and returns argv; cwd is set by the caller.
FORMATS = [
    {"id": "zip",    "label": "zip",    "ext": ".zip",
     "tools": ["zip"],
     "argv": lambda dst, names: [_tool("zip"), "-r", "-q", dst, "--"] + names},
    {"id": "tar.gz", "label": "tar.gz", "ext": ".tar.gz",
     "tools": ["tar", "gzip"],
     "argv": lambda dst, names: [_tool("tar"), "-czf", dst, "--"] + names},
    {"id": "tar.xz", "label": "tar.xz", "ext": ".tar.xz",
     "tools": ["tar", "xz"],
     "argv": lambda dst, names: [_tool("tar"), "-cJf", dst, "--"] + names},
    {"id": "7z",     "label": "7z",     "ext": ".7z",
     "tools": ["7z"],   # resolved specially — see _seven_bin
     "argv": lambda dst, names: [_seven_bin(), "a", "-bd", "-y", dst, "--"] + names},
]


def _spec(fmt):
    return next((f for f in FORMATS if f["id"] == fmt), None)


def _available(spec):
    if spec["id"] == "7z":
        return _seven_bin() is not None
    return all(_resolved(t) for t in spec["tools"])


def available_formats():
    """The archive targets this machine can actually build, in menu order."""
    return [{"id": f["id"], "label": f["label"]}
            for f in FORMATS if _available(f)]


def out_path_for(paths, fmt):
    """Where the archive lands: next to the selection, never clobbering. One
    file `photo.png` -> `photo.zip`; one directory `stuff` -> `stuff.zip`;
    several items -> the parent directory's name (or `archive`)."""
    spec = _spec(fmt)
    ext = spec["ext"]
    parent = os.path.dirname(paths[0]) or "."
    if len(paths) == 1:
        name = os.path.basename(paths[0].rstrip("/"))
        base = name if os.path.isdir(paths[0]) else os.path.splitext(name)[0]
    else:
        base = os.path.basename(parent) or "archive"
    cand = os.path.join(parent, base + ext)
    n = 2
    while os.path.lexists(cand):
        cand = os.path.join(parent, "%s-%d%s" % (base, n, ext))
        n += 1
    return cand


def _human(b):
    b = float(b)
    for u in ("B", "K", "M", "G"):
        if b < 1024 or u == "G":
            return "%dB" % b if u == "B" else "%.1f%s" % (b, u)
        b /= 1024


class ArchiveConv(QObject):
    """Bridge for the "compress to <format>" archive rows.

    `formats()` is what the submenu is built from; `start(paths, fmt)` runs the
    archiver asynchronously (QProcess, never blocking the UI) and reports only
    through desktop toasts — a persistent "archiving..." that morphs into the
    result, the same notify-send --replace-id trick the video side uses.
    """

    finished = Signal(str)   # output path ("" on failure) — QML reselects it

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs = {}      # dst path -> job dict, also the "already running" set

    def _toast(self, job, title, body, urgency=None, persist=False):
        nid = _toast_send(title, body, urgency=urgency, replace_id=job.get("nid"),
                          persist=persist)
        if nid is not None:
            job["nid"] = nid

    @Slot(result="QVariant")
    def formats(self):
        return available_formats()

    @Slot(list, str)
    def start(self, paths, fmt):
        """Archive `paths` (the current selection) into `fmt`, beside them.
        Refusals — nothing selected, a format whose tool vanished, an archive
        already building at that name — come back as a toast, never a no-op."""
        paths = [str(p) for p in paths if str(p)]
        spec = _spec(fmt)
        if spec is None or not paths:
            return
        if not _available(spec):
            self._toast({}, "can't compress",
                        "no tool for %s on this machine" % spec["label"],
                        urgency="normal")
            return
        dst = out_path_for(paths, fmt)
        if dst in self._jobs:
            return
        parent = os.path.dirname(paths[0]) or "."
        names = [os.path.basename(p.rstrip("/")) for p in paths]
        argv = spec["argv"](dst, names)
        job = {"dst": dst, "src0": paths[0], "count": len(paths),
               "label": spec["label"], "nid": None, "err": ""}
        self._jobs[dst] = job
        what = names[0] if len(names) == 1 else "%d items" % len(names)
        self._toast(job, "compressing to " + spec["label"],
                    "%s\npacking %s" % (os.path.basename(dst), what), persist=True)
        self._spawn(job, argv, parent)

    def _spawn(self, job, argv, cwd):
        proc = QProcess(self)
        job["proc"] = proc
        proc.setWorkingDirectory(cwd)
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.readyReadStandardError.connect(lambda: self._on_stderr(job))
        proc.finished.connect(lambda code, status: self._on_done(job, code))
        proc.errorOccurred.connect(lambda _e: self._on_error(job))
        proc.start(argv[0], argv[1:])

    def _on_stderr(self, job):
        try:
            text = bytes(job["proc"].readAllStandardError()).decode("utf-8", "replace")
        except (RuntimeError, UnicodeError):
            return
        for line in text.splitlines():
            if line.strip():
                job["err"] = line.strip()

    def _on_error(self, job):
        if job["dst"] in self._jobs:
            self._fail(job, job["err"] or "archiver could not be started")

    def _on_done(self, job, code):
        if job["dst"] not in self._jobs:
            return
        dst = job["dst"]
        if code == 0 and os.path.exists(dst):
            self._toast(job, "compressed: " + os.path.basename(dst),
                        "%s\n%s" % (_human(os.path.getsize(dst)), job["label"]))
            self._cleanup(job)
            self.finished.emit(dst)
            return
        self._fail(job, job["err"] or "archiver exited %d" % code)

    def _fail(self, job, msg):
        try:
            if os.path.exists(job["dst"]):
                os.unlink(job["dst"])      # never leave a truncated archive behind
        except OSError:
            pass
        self._toast(job, "compress failed: " + os.path.basename(job["dst"]),
                    msg[:200], urgency="critical")
        self._cleanup(job)
        self.finished.emit("")

    def _cleanup(self, job):
        self._jobs.pop(job["dst"], None)
        proc = job.get("proc")
        if proc is not None:
            proc.deleteLater()
