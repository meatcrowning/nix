#!/usr/bin/env python3
"""remote-test — the `:host` and `:DRIVE` address syntax, offline.

Exercises remote.py's two pure halves: `parse()` (typed text -> user, host,
absolute remote path) and `pretty()` (mounted local path -> the address that
would be typed to reach it), plus the drive lookup on either side of a mount.
Nothing here mounts, connects or resolves a name — the only I/O is reading this
machine's hostname and listing a temp tree that stands in for `DRIVE_ROOT`, so
it runs anywhere, gives the same answer whatever is plugged in, and touches
nothing the user can see.

The property that matters most is the ROUND TRIP: the address bar shows
`pretty(path)` and submits it back through `parse()`, so a path that does not
survive the loop is an address bar that walks somewhere else the moment you
press Enter on it unchanged.

    ./tools/remote-test.py
"""
import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FILER = os.path.dirname(HERE)
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))

import remote  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (("  " + detail) if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def main():
    remote.DEFAULT_USER = "lam"
    mp = remote.mountpoint("lam", "top")

    # ---- parse: the shapes the bar accepts -----------------------------------
    check("bare host is the remote home",
          remote.parse(":top") == ("lam", "top", "/home/lam"),
          repr(remote.parse(":top")))
    check("subpath hangs off the home",
          remote.parse(":top/dl/iso") == ("lam", "top", "/home/lam/dl/iso"))
    check("whitespace is trimmed",
          remote.parse("  :top  ") == ("lam", "top", "/home/lam"))
    check("host case is normalised",
          remote.parse(":TOP") == ("lam", "top", "/home/lam"))
    check("explicit user gets that user's home",
          remote.parse(":joe@top") == ("joe", "top", "/home/joe"))
    check("root's home is /root, not /home/root",
          remote.parse(":root@top") == ("root", "top", "/root"))
    check("second colon means an absolute remote path",
          remote.parse(":top:/etc/nixos") == ("lam", "top", "/etc/nixos"))
    check("a dotted host is a host",
          remote.parse(":top.lan") == ("lam", "top.lan", "/home/lam"))
    check("trailing slash normalises away",
          remote.parse(":top/dl/") == ("lam", "top", "/home/lam/dl"))

    # ---- parse: what must stay a LOCAL path ----------------------------------
    # Anything parse() claims, the address bar stops treating as a path — so a
    # false positive here is a local directory that becomes unreachable.
    for bad in ("/home/lam", "~/dl", "", "   ", ":", ":/tmp", ":/", "::/etc",
                ":top:etc", ":-top", ":to p"):
        check("not an address: %r" % bad, remote.parse(bad) is None,
              repr(remote.parse(bad)))
    check("a local path with a colon in it is still a path",
          remote.parse("/home/lam/a:b") is None)

    # ---- this machine needs no mount ----------------------------------------
    me = socket.gethostname().split(".")[0].lower()
    spec = remote.parse(":" + me)
    check("own hostname parses like any other host",
          spec is not None and spec[1] == me)
    check("own hostname is a local name", me in remote._local_names())
    check("localhost is a local name", "localhost" in remote._local_names())

    # ---- drives: `:SSD` on either machine ------------------------------------
    # DRIVE_ROOT is redirected at a temp tree so the result does not depend on
    # what happens to be plugged into the machine running the test.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        droot = os.path.join(td, "media")
        os.makedirs(os.path.join(droot, "SSD"))
        os.makedirs(os.path.join(droot, "arc"))
        remote.DRIVE_ROOT = droot
        me = socket.gethostname().split(".")[0].lower()
        dmp = remote.mountpoint("lam", remote.DRIVE_HOST)

        check("a mounted drive resolves locally, no host",
              remote.parse(":SSD") == ("lam", me, droot + "/SSD"),
              repr(remote.parse(":SSD")))
        check("drive case is folded, the on-disk name comes back",
              remote.parse(":ssd") == ("lam", me, droot + "/SSD"))
        check("a subpath hangs off the drive",
              remote.parse(":arc/flac/x") == ("lam", me, droot + "/arc/flac/x"))
        check("an unmounted name stays a host",
              remote.parse(":nope") == ("lam", "nope", "/home/lam"))
        check("an explicit user is never a drive",
              remote.parse(":joe@SSD") == ("joe", "ssd", "/home/joe"))
        check("an explicit remote path is never a drive",
              remote.parse(":SSD:/etc") == ("lam", "ssd", "/etc"))

        # what open()'s worker consults once a name has failed to resolve
        check("drive_addr reads a bare name", remote.drive_addr(":SSD") == ("SSD", ""))
        check("drive_addr keeps the subpath",
              remote.drive_addr(":SSD/a/b") == ("SSD", "a/b"))
        for bad in (":joe@x", ":x:/etc", "/tmp", "", ":", ":/tmp"):
            check("drive_addr declines %r" % bad, remote.drive_addr(bad) is None)

        # pretty: one drive, two paths to it, one address
        check("a local drive is ':NAME'", remote.pretty_of(droot + "/SSD") == ":SSD")
        check("a local drive subpath keeps its tail",
              remote.pretty_of(droot + "/SSD/flac/x") == ":SSD/flac/x")
        check("the drive root itself is not an address",
              remote.pretty_of(droot) == droot)
        check("the drive host's copy reads as the SAME drive address",
              remote.pretty_of(dmp + droot + "/SSD/flac/x") == ":SSD/flac/x")
        check("a drive missing from the drive host's mount is still an address",
              remote.pretty_of(dmp + droot + "/usb") == ":usb")

        # round trip, local half: what the bar shows lands back where it was
        for p in (droot + "/SSD", droot + "/arc/flac/x"):
            addr = remote.pretty_of(p)
            spec = remote.parse(addr)
            check("round trip %s -> %s" % (p.replace(droot, "$D"), addr),
                  spec is not None and spec[1] == me and spec[2] == p, repr(spec))
        # ... and the remote half, which parse() alone cannot finish: the
        # address must at least still NAME that drive to the worker.
        check("a remote drive address round-trips as a drive name",
              remote.drive_addr(remote.pretty_of(dmp + droot + "/SSD/x"))
              == ("SSD", "x"))

        # the remote half of the lookup, against a stand-in for a mounted
        # drive host: this is what the worker calls once sshfs is up.
        fmp = os.path.join(td, "mnt")
        os.makedirs(fmp + droot + "/SSD/flac")
        check("a drive is found under the mount, case folded",
              remote._drive_on_mount(fmp, "ssd", "flac")
              == fmp + droot + "/SSD/flac")
        check("a drive that is not on the mount is None",
              remote._drive_on_mount(fmp, "usb", "") is None)

        # an unreadable DRIVE_ROOT (nothing plugged in, on either machine) must
        # leave every address a host address rather than raising
        remote.DRIVE_ROOT = os.path.join(td, "nothing-here")
        check("no drive root: names stay hosts",
              remote.parse(":SSD") == ("lam", "ssd", "/home/lam"))
        check("no drive root: drive_match is None, not an error",
              remote.drive_match("SSD") is None)
    remote.DRIVE_ROOT = "/run/media/lam"

    # ---- pretty: the reverse map --------------------------------------------
    check("a local path is returned unchanged",
          remote.pretty_of("/home/lam/dl") == "/home/lam/dl")
    check("the remote home is ':host'",
          remote.pretty_of(mp + "/home/lam") == ":top")
    check("a subpath keeps its tail",
          remote.pretty_of(mp + "/home/lam/dl") == ":top/dl")
    check("outside the home takes the explicit-path form",
          remote.pretty_of(mp + "/etc/nixos") == ":top:/etc/nixos")
    check("the mount root itself is the remote's /",
          remote.pretty_of(mp) == ":top:/")
    check("a non-default user is named",
          remote.pretty_of(remote.mountpoint("joe", "top") + "/home/joe/x")
          == ":joe@top/x")
    check("a home-prefix near-miss is NOT rewritten as a subpath",
          remote.pretty_of(mp + "/home/lambda") == ":top:/home/lambda")

    # ---- the round trip ------------------------------------------------------
    # pretty(p) is what the bar shows; parse() is what pressing Enter on it
    # does. They must land back on p.
    for p in (mp + "/home/lam", mp + "/home/lam/dl/iso", mp + "/etc/nixos",
              mp, remote.mountpoint("joe", "top") + "/home/joe/x",
              mp + "/home/lambda"):
        addr = remote.pretty_of(p)
        spec = remote.parse(addr)
        back = os.path.normpath(remote.mountpoint(spec[0], spec[1]) + spec[2]) if spec else None
        check("round trip %s -> %s" % (p.replace(remote.MOUNT_ROOT, "$MP"), addr),
              back == os.path.normpath(p), repr(back))

    # ---- prefetch: warms remote paths only, and never throws --------------
    # It is fire-and-forget off the click path, so the contract is narrow: a
    # local path must not spawn a thread at all (the kernel has already cached
    # it, and a needless full read of a big local file is pure cost), and
    # nothing it can hit — a vanished file, a dead mount — may reach the caller.
    import tempfile
    import threading
    import time
    with tempfile.TemporaryDirectory() as td:
        remote.MOUNT_ROOT = os.path.join(td, "filer-remote")
        fake = os.path.join(remote.MOUNT_ROOT, "lam@fake")
        os.makedirs(fake)
        f = os.path.join(fake, "x.bin")
        with open(f, "wb") as h:
            h.write(b"\0" * (1 << 20))
        r = remote.Remote()
        before = threading.active_count()
        r.prefetch("/etc/hostname")
        r.prefetch("")
        check("a local path spawns no prefetch",
              threading.active_count() == before)
        r.prefetch(f)
        r.prefetch(f)                     # the second must not double up
        check("a remote path is warmed once",
              threading.active_count() <= before + 1)
        for _ in range(200):              # let it finish
            if not r._warming:
                break
            time.sleep(0.01)
        check("the warm set empties again", not r._warming)
        r.prefetch(os.path.join(fake, "gone.bin"))
        for _ in range(200):
            if not r._warming:
                break
            time.sleep(0.01)
        check("a missing file is swallowed, not raised", not r._warming)

    print()
    if FAILED:
        print("%d FAILED: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
