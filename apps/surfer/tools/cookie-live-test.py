#!/usr/bin/env python3
"""Regression test for the LIVE cookie merge — `sync.py fetch`'s decision half.

The live path cannot use merge_cookies: surfer owns the profile while it runs,
so nothing may write that file. `winners_against_local()` decides instead, and
Chromium's cookie store does the write (main.py `_cookie_sync_live`). This test
pins the decision rule, because getting it wrong is silent — a stale cookie
injected over a fresh one logs you out on the machine that was right.

Synthetic databases only; it never reads the real profile.

    /usr/bin/python3 apps/surfer/tools/cookie-live-test.py
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync  # noqa: E402

DDL = """create table cookies (
  creation_utc integer, host_key text, top_frame_site_key text, name text,
  value text, path text, expires_utc integer, is_secure integer,
  is_httponly integer, last_update_utc integer, has_expires integer,
  has_cross_site_ancestor integer, source_scheme integer, source_port integer
)"""

FUTURE = sync.now_chromium() + 86400 * 1_000_000
PAST = sync.now_chromium() - 86400 * 1_000_000


def row(name, last_update, expires=FUTURE, has_expires=1, value="v"):
    return {
        "host_key": "example.com", "top_frame_site_key": "", "name": name,
        "value": value, "path": "/", "has_cross_site_ancestor": 0,
        "source_scheme": 2, "source_port": 443, "last_update_utc": last_update,
        "has_expires": has_expires, "expires_utc": expires, "is_secure": 1,
        "is_httponly": 0, "creation_utc": 1,
    }


def main():
    d = tempfile.mkdtemp(prefix="surfer-cookie-live-test-")
    db = os.path.join(d, "Cookies")
    con = sqlite3.connect(db)
    con.execute(DDL)
    # what WE already have
    con.execute(
        "insert into cookies (host_key, top_frame_site_key, name, value, path,"
        " has_cross_site_ancestor, source_scheme, source_port, last_update_utc,"
        " has_expires, expires_utc) values (?,?,?,?,?,?,?,?,?,?,?)",
        ("example.com", "", "stale_here", "old", "/", 0, 2, 443, 100, 1, FUTURE),
    )
    con.execute(
        "insert into cookies (host_key, top_frame_site_key, name, value, path,"
        " has_cross_site_ancestor, source_scheme, source_port, last_update_utc,"
        " has_expires, expires_utc) values (?,?,?,?,?,?,?,?,?,?,?)",
        ("example.com", "", "fresh_here", "new", "/", 0, 2, 443, 900, 1, FUTURE),
    )
    con.commit()
    con.close()

    sync.cookies_path = lambda: db  # never touch the real profile

    payload = {"columns": list(row("x", 0).keys()), "rows": [
        row("stale_here", 500),           # top is NEWER  -> wins
        row("fresh_here", 500),           # top is OLDER  -> loses
        row("only_on_top", 500),          # we lack it    -> wins
        row("expired", 999, expires=PAST),  # dead         -> dropped
    ]}

    got = {r["name"] for r in sync.winners_against_local(payload)}
    want = {"stale_here", "only_on_top"}

    ok = got == want
    for n, why in (("stale_here", "top newer -> inject"),
                   ("fresh_here", "ours newer -> keep ours"),
                   ("only_on_top", "absent here -> inject"),
                   ("expired", "expired -> never resurrect")):
        mark = "ok " if ((n in got) == (n in want)) else "FAIL"
        print(f"  [{mark}] {n:12} {why}")

    # a profile we cannot read must not silently drop the sync
    sync.cookies_path = lambda: os.path.join(d, "does-not-exist")
    n_fallback = len(sync.winners_against_local(payload))
    fb_ok = n_fallback == len(payload["rows"])
    print(f"  [{'ok ' if fb_ok else 'FAIL'}] unreadable profile -> "
          f"fall back to all {n_fallback} rows, let setCookie arbitrate")

    print("PASS" if (ok and fb_ok) else "FAIL")
    return 0 if (ok and fb_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
