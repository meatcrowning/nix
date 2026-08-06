#!/usr/bin/env python3
"""order-test — `--order` must not stat what it was handed.

This exists because of one measurement. Opening an image from filer on a folder
that lives on the other machine took **4.07s to the first frame, 3.70s of it
inside `images_for()`** — `order_from()` was calling `os.path.isfile()` on every
path in the order file, and over a network mount that is one round trip each.
891 files in the folder, 890 of which nobody had asked to see. The same click on
a local folder was instant, which is exactly why it went unnoticed: the cost is
invisible until the filesystem is not local. `feh`, which does not do it, opened
the same files immediately.

So the guard is not "is it fast" — a timing assertion on a local temp directory
would pass with the bug back in. It **counts the filesystem calls** and requires
the count not to grow with the number of entries. That is the property that was
violated, stated directly.

Also checks the rest of the order-file contract, which is what makes it safe to
stop stat-ing: extension filtering still happens, the file is still consumed,
and a list that does not contain the clicked file is still rejected so the
caller falls back to scanning the directory.

Offscreen, no window, temp directory only.

    ./tools/order-test.py
"""
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

VIEWER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, VIEWER)
sys.path.insert(0, os.path.join(os.path.dirname(VIEWER), "pylib"))

import main as viewermain  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


class CountFS:
    """Count every path-touching call `order_from` could plausibly make. A
    context manager rather than a mock: the real functions still run, so the
    test is measuring the production path and not a stub of it."""

    NAMES = ("stat", "lstat", "access")

    def __enter__(self):
        self.n = 0
        self._orig = {}
        for mod, name in [(os, n) for n in self.NAMES] + [(os.path, "isfile"),
                                                          (os.path, "exists"),
                                                          (os.path, "isdir")]:
            self._orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, self._wrap(getattr(mod, name)))
        return self

    def _wrap(self, fn):
        def inner(*a, **k):
            self.n += 1
            return fn(*a, **k)
        return inner

    def __exit__(self, *exc):
        for (mod, name), fn in self._orig.items():
            setattr(mod, name, fn)
        return False


def order_file(tmp, paths):
    fd, f = tempfile.mkstemp(dir=tmp, prefix="order-")
    os.write(fd, "\0".join(paths).encode("utf-8", "surrogateescape"))
    os.close(fd)
    return f


def main():
    tmp = tempfile.mkdtemp(prefix="t_order-")
    # _consume() only deletes inside a temp root, and that is where we are.
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all order checks passed")
    return 0


def run(tmp):
    small = [os.path.join(tmp, "img%03d.png" % i) for i in range(10)]
    large = [os.path.join(tmp, "img%03d.png" % i) for i in range(400)]
    for p in large:
        open(p, "wb").close()

    # ---- THE regression guard --------------------------------------------
    with CountFS() as c10:
        got10 = viewermain.order_from(order_file(tmp, small), small[3])
    with CountFS() as c400:
        got400 = viewermain.order_from(order_file(tmp, large), large[3])
    check("a 10-entry order file resolves", got10 is not None and len(got10[0]) == 10,
          got10 and len(got10[0]))
    check("a 400-entry order file resolves", got400 is not None and len(got400[0]) == 400,
          got400 and len(got400[0]))
    check("the filesystem calls do NOT grow with the number of entries "
          "(10 -> %d calls, 400 -> %d)" % (c10.n, c400.n),
          c400.n <= c10.n + 2, "%d vs %d" % (c10.n, c400.n))
    check("...and there are only a handful of them at all", c400.n <= 4, c400.n)

    # ---- what still has to be true for that to be safe --------------------
    mixed = [os.path.join(tmp, "a.png"), os.path.join(tmp, "notes.txt"),
             os.path.join(tmp, "b.jpg"), os.path.join(tmp, "sub")]
    for p in mixed[:3]:
        open(p, "wb").close()
    os.mkdir(mixed[3])
    got = viewermain.order_from(order_file(tmp, mixed), mixed[0])
    check("non-media entries are still filtered out by extension",
          got is not None and [e["name"] for e in got[0]] == ["a.png", "b.jpg"],
          got and [e["name"] for e in got[0]])
    check("...positioned on the clicked file", got and got[1] == 0, got and got[1])

    f = order_file(tmp, small)
    viewermain.order_from(f, small[3])
    check("the order file is consumed", not os.path.exists(f))

    f = order_file(tmp, small)
    got = viewermain.order_from(f, os.path.join(tmp, "elsewhere.png"))
    check("an order file that does not contain the clicked file is rejected",
          got is None, got)
    check("...and consumed anyway, so it cannot pile up", not os.path.exists(f))

    check("an unreadable order file is None, not an exception",
          viewermain.order_from(os.path.join(tmp, "nope"), small[0]) is None)

    # ---- and end to end through images_for --------------------------------
    with CountFS() as c:
        entries, idx, panes = viewermain.images_for(
            ["--order", order_file(tmp, large), large[7]])
    check("images_for uses the order file wholesale",
          len(entries) == 400 and idx == 7 and panes == 1, (len(entries), idx, panes))
    check("...for a bounded number of filesystem calls, whatever the folder size",
          c.n <= 8, c.n)


if __name__ == "__main__":
    sys.exit(main())
