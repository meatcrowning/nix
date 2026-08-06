#!/usr/bin/env python3
"""remote-test — the `:host` address syntax, offline.

Exercises remote.py's two pure halves: `parse()` (typed text -> user, host,
absolute remote path) and `pretty()` (mounted local path -> the address that
would be typed to reach it). Nothing here mounts, connects or resolves a name —
the only I/O is reading this machine's hostname, so it runs anywhere and
touches nothing the user can see.

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
