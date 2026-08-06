"""remote — `:top` in the address bar: browse another machine's filesystem.

Type `:top` into filer's path bar and you land in lam's home on `top`. The
whole feature is one sshfs mount plus a name rewrite, deliberately:

  * **The mount is the remote's `/`, not its home.** Mounting the home
    directory would need one mountpoint per (host, root) pair — `:top` and
    `:top:/etc` would collide on the same directory name — and it would make
    `pretty()` (the reverse map, below) ambiguous. One mount per host means
    every path on that machine is addressable, `^` walks out of the home the
    way it does locally, and the rewrite is a plain prefix swap.
  * **Everything downstream stays ordinary local-path code.** The tree, the
    preview grid, drag and drop, copy/move, `viewer` — none of them learn
    about remotes, because by the time they see a path it is a real path under
    the mountpoint.
  * **Mounting happens off the GUI thread.** An ssh handshake to a machine
    that is asleep takes as long as `ConnectTimeout`; doing that in the
    address-bar handler would freeze the window. `open()` returns at once and
    the navigation happens on the `ready` signal.
  * **It cannot fail silently** (docs/DESIGN.md 10.4): a mount that takes a
    moment posts a live toast, and a mount that fails replaces it with the
    reason ssh gave, rather than leaving the path bar sitting on the old
    directory with no explanation.

Address syntax, all of it:

    :top                 lam@top, that machine's /home/lam
    :top/dl/iso          ... and a subdirectory of it
    :root@top            another user's home (/root for root, /home/<u> else)
    :top:/etc/nixos      an absolute path on the remote, home not assumed

An address naming THIS machine resolves locally with no mount at all, so
`:book` on book is simply /home/lam.

Requirements, and they differ per host: `sshfs` comes from the nix wrapper on
`top` (`home/prog/filer.nix`) and from Fedora's `fuse-sshfs` on `book`, which
is why it is resolved through `notify.tool()` rather than hardcoded. Auth is
key-only (`BatchMode=yes`) — a password prompt has no terminal to appear on and
would hang the mount until the timeout. Unknown host keys are accepted on first
use (`accept-new`), the same answer a person gives the interactive prompt.

Two things this does NOT try to be: it is not a fast filesystem (thumbnails of
a remote directory pull the files over the wire), and a symlink on the remote
pointing at an absolute path — `/nix/store/...`, say — resolves against THIS
machine's copy of that path, because sshfs hands the link text through
untranslated. Both are properties of sshfs, not of filer.
"""
import os
import re
import socket
import subprocess
import threading

from PySide6.QtCore import QObject, Slot, Signal

from notify import tool, toast

# Where the mounts live. $XDG_RUNTIME_DIR is right for them: they are session
# state, and a logout that tears the directory down takes the stale mountpoints
# with it. One directory per host, named `user@host`.
MOUNT_ROOT = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp",
                          "filer-remote")

DEFAULT_USER = os.environ.get("USER") or "lam"

_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# reconnect + keepalives so a laptop that slept comes back rather than leaving
# a wedged mountpoint; BatchMode because there is no terminal for a passphrase
# prompt; a short ConnectTimeout because the user is waiting on the address bar.
#
# The three that are about SPEED, all measured book -> top over 5GHz wifi, where
# raw ssh tops out at 39 MB/s and a single sshfs stream reaches 30:
#
#   auto_cache   Re-reading a file is otherwise the FULL transfer again, every
#                time — and the common case here is exactly a re-read: the
#                preview grid thumbnails an image, then you click it and viewer
#                reads the same bytes seconds later. Measured 30 MB/s -> 1.5
#                GB/s on the second read of a 30 MB file (67x), because the
#                page cache is now allowed to answer. `auto_cache` and not
#                `kernel_cache`: it revalidates against the remote's size and
#                mtime, where kernel_cache never revalidates at all. The
#                residual risk is a remote file rewritten to the SAME byte
#                length within `cache_timeout` — measured, that one is served
#                stale; a size change is picked up at once.
#   max_conns=4  One ssh connection is a single stream, so four parallel reads
#                (the thumbnail pool's width) share 30 MB/s. Four connections
#                reach 37 MB/s on the same test — the link's own ceiling. No
#                cost to a single stream.
#   cache_timeout=5  Was 20. With auto_cache the attribute cache also bounds how
#                long stale CONTENT can be served, and 20s of that is too long
#                for a file browser; a directory listing of 1191 entries costs
#                0.04s cached and 0.11s cold, so revalidating four times as
#                often is not something you can feel.
SSHFS_OPTS = [
    "reconnect",
    "ServerAliveInterval=15",
    "ServerAliveCountMax=3",
    "ConnectTimeout=8",
    "BatchMode=yes",
    "StrictHostKeyChecking=accept-new",
    "idmap=user",          # remote uid/gid shown as ours; we are the same user
    "dir_cache=yes",
    "cache_timeout=5",
    "auto_cache",
    "max_conns=4",
]

# How much of a file `prefetch()` pulls. Big enough to cover essentially every
# still image whole; small enough that clicking a 4 GB video does not try to
# haul it across the wifi. A video player streams, and the head is all it needs
# to start.
PREFETCH_MAX = 64 * 1024 * 1024


def _local_names():
    """Names that mean "this machine", so `:book` on book needs no ssh."""
    names = {"localhost"}
    h = socket.gethostname()
    if h:
        names.add(h.lower())
        names.add(h.lower().split(".")[0])
    return names


def parse(text):
    """`:`-address -> (user, host, path) with `path` absolute on the remote, or
    None if `text` is not a remote address at all (the ordinary local-path case,
    which the caller must keep handling itself)."""
    t = (text or "").strip()
    if not t.startswith(":"):
        return None
    t = t[1:]
    if not t or t.startswith("/"):
        return None                     # ":" alone, or ":/tmp" — no host named
    if ":" in t:                        # explicit remote root: :host:/etc
        hostpart, _, path = t.partition(":")
        if not path.startswith("/"):
            return None
    else:                               # home-relative: :host or :host/sub
        hostpart, sep, sub = t.partition("/")
        path = ""                       # filled in once the user is known
    user, _, host = hostpart.rpartition("@")
    user = user or DEFAULT_USER
    if not host or not _HOST_RE.match(host):
        return None
    if not path:
        home = "/root" if user == "root" else "/home/" + user
        path = home + ("/" + sub if sub else "")
    return user, host.lower(), os.path.normpath(path)


def mountpoint(user, host):
    return os.path.join(MOUNT_ROOT, "%s@%s" % (user, host))


def pretty_of(path):
    """The inverse of `parse()`: a path under a mount, written as the address
    that would be typed to reach it. Round-trips — feed the result back to
    `parse()` and you land on the same path again — which is what makes it safe
    to put in the address bar, where pressing Enter on the unchanged text must
    not navigate somewhere else. Anything not under a mount is returned as-is."""
    p = str(path or "")
    root = MOUNT_ROOT.rstrip("/") + "/"
    if not p.startswith(root):
        return p
    name, _, sub = p[len(root):].partition("/")
    user, _, host = name.rpartition("@")
    if not host:
        return p
    head = host if user == DEFAULT_USER else name
    sub = "/" + sub if sub else ""
    home = "/root" if user == "root" else "/home/" + user
    if sub == home or sub.startswith(home + "/"):
        return ":" + head + sub[len(home):]
    return ":" + head + ":" + (sub or "/")


def _live(mp):
    """Is `mp` a mount we can actually read? A dropped sshfs leaves the
    mountpoint in place and every call on it fails with ENOTCONN, so `ismount`
    alone would have us navigate into a dead directory."""
    if not os.path.ismount(mp):
        return False
    try:
        os.listdir(mp)
        return True
    except OSError:
        return False


def _unmount(mp):
    """Lazy-unmount a mountpoint, for the stale case. Lazy because a dead sshfs
    holds references that a plain unmount refuses to break."""
    for prog in ("fusermount3", "fusermount"):
        try:
            r = subprocess.run([tool(prog), "-uz", mp],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


class Remote(QObject):
    """The `Remote` context property. QML calls `open()` with the typed text and
    navigates on `ready`; `failed` is informational (the toast is posted here,
    where the reason is)."""

    ready = Signal(str)         # a real, mounted, local path — go there
    failed = Signal(str)        # host that could not be reached

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = set()      # hosts with a mount attempt in flight
        self._warming = set()   # paths a prefetch thread is already pulling
        self._lock = threading.Lock()

    @Slot(str, result=bool)
    def isAddr(self, text):
        """Does this look like `:host...`? The address bar asks before deciding
        whether to treat the text as a local path."""
        return parse(text) is not None

    @Slot(str, result=str)
    def pretty(self, path):
        """What the address bar shows for `path` — see `pretty_of()`."""
        return pretty_of(path)

    @Slot(str)
    def prefetch(self, path):
        """Start pulling `path` into the page cache, now, in the background.

        Called the instant a remote file is opened, BEFORE the app that will
        show it is launched. Measured on book: viewer takes 0.22s to get its
        QML up and only then reads the file, and the wire runs at ~30 MB/s — so
        starting the transfer at click time rather than at read time hides
        about 6 MB of it behind a startup that was happening anyway, and the
        rest of it overlaps instead of following. It works only because the
        mount now has `auto_cache`: without it the second reader pays the full
        transfer again and this would make things strictly worse.

        A no-op for a local path (nothing to warm — the kernel already did it)
        and for a file already being warmed. Never raises: a prefetch that
        fails costs nothing, because the real read is still to come."""
        p = str(path or "")
        if not p.startswith(MOUNT_ROOT.rstrip("/") + "/"):
            return
        with self._lock:
            if p in self._warming:
                return
            self._warming.add(p)
        threading.Thread(target=self._warm, args=(p,), daemon=True).start()

    def _warm(self, p):
        try:
            left = PREFETCH_MAX
            with open(p, "rb", buffering=0) as f:
                while left > 0 and f.read(min(4 << 20, left)):
                    left -= 4 << 20
        except OSError:
            pass
        finally:
            with self._lock:
                self._warming.discard(p)

    @Slot(str)
    def open(self, text):
        """Resolve a `:host` address and emit `ready` with a browsable local
        path. Mounts first if it has to, on a worker thread."""
        spec = parse(text)
        if spec is None:
            return
        user, host, path = spec
        if host in _local_names() and user == DEFAULT_USER:
            self.ready.emit(path)       # ":book" on book is just a local path
            return
        mp = mountpoint(user, host)
        target = os.path.normpath(mp + path)
        if _live(mp):
            self.ready.emit(target)
            return
        if host in self._busy:          # a second Enter while the first connects
            return
        self._busy.add(host)
        threading.Thread(target=self._mount, args=(user, host, mp, target),
                         daemon=True).start()

    # ---- worker thread ----
    # Signals emitted from here are queued onto the GUI thread by Qt, the same
    # way VtbClient's reader thread delivers a titlebar click.
    def _mount(self, user, host, mp, target):
        tid = toast("connecting to " + host, "mounting over ssh", persist=True)
        try:
            ok, err = self._do_mount(user, host, mp)
        finally:
            self._busy.discard(host)
        if ok:
            if tid:
                toast("connecting to " + host, "mounted", replace_id=tid)
            self.ready.emit(target)
        else:
            toast("cannot reach " + host, err[:400] or "sshfs failed",
                  urgency="critical", replace_id=tid)
            self.failed.emit(host)

    def _do_mount(self, user, host, mp):
        # Already up — two windows, or two panes, can ask at once, and sshfs
        # over a live mountpoint fails with a bare "Permission denied" that
        # reads as an auth problem and is not one.
        if _live(mp):
            return True, ""
        if os.path.exists(mp) and not _live(mp):
            _unmount(mp)                # stale mount from a previous session
        try:
            os.makedirs(mp, exist_ok=True, mode=0o700)
        except OSError as e:
            return False, str(e)
        sshfs = tool("sshfs")
        argv = [sshfs, "%s@%s:/" % (user, host), mp]
        for o in SSHFS_OPTS:
            argv += ["-o", o]
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            return False, "sshfs is not installed"
        except subprocess.TimeoutExpired:
            _unmount(mp)
            return False, "timed out connecting"
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)
        if r.returncode != 0 or not _live(mp):
            msg = (r.stderr or r.stdout or "").strip().splitlines()
            return False, (msg[-1] if msg else "sshfs exited %d" % r.returncode)
        return True, ""
