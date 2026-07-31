#!/usr/bin/env python3
"""Headless regression test for surfer's ad-blocking engine.

Drives `AdBlocker` + `Cosmetic` from main.py directly — no window, no
QtWebEngine initialisation, never the user's live browser (see
apps/AGENTS.md: the user does every visual check).

It runs against a SCRATCH $XDG_CACHE_HOME/$XDG_CONFIG_HOME, so the first run
downloads the full subscription set and the uBO resource tarball (~7 MB, about
a minute) and later runs reuse them. Point $SURFER_TEST_HOME somewhere durable
to keep that cache between runs.

    python3 tools/adblock-test.py [--home DIR]

Checks, in order:

  1. the engine builds and `injected_script` is NON-EMPTY for sites with known
     scriptlet rules — the whole point of loading the resource library, and the
     thing that was silently broken (no resources -> no scriptlet ever fires,
     so a first-party pre-roll ad has nothing to stop it);
  2. 4chan's self-hosted /adv/ ads are blocked despite EasyList's explicit
     `@@||4cdn.org/adv/` allow-list exceptions, and the site's real assets are
     NOT;
  3. generic cosmetic filtering still works, i.e. `generichide` was not turned
     on globally by the mis-parsed hide-exception rule `_sanitize` repairs;
  4. procedural filters reach the injector — from the engine's own
     `procedural_actions` on top's fork, or from AdBlocker's raw-list pre-scan
     on book's 0.6.0, whichever this interpreter has.

Run it under BOTH pythons when you touch the resource or procedural code: the
surfer wrapper's pyEnv (jampe fork, adblock-rust 0.12.5) and a python holding
PyPI `adblock` 0.6.0, which is what book gets.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=os.environ.get(
        "SURFER_TEST_HOME", "/tmp/surfer-adblock-test"))
    args = ap.parse_args()

    home = Path(args.home)
    (home / "cache").mkdir(parents=True, exist_ok=True)
    (home / "config").mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CACHE_HOME"] = str(home / "cache")
    os.environ["XDG_CONFIG_HOME"] = str(home / "config")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
    os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
    os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back
    os.environ["SURFER_NO_SINGLETON"] = "1"

    import main as surfer                                   # noqa: E402

    blocker = surfer.AdBlocker()
    cosmetic = surfer.Cosmetic(blocker)

    print("waiting for the background compile/fetch ...", flush=True)
    deadline = time.time() + 600
    while time.time() < deadline:
        if blocker._engine is not None and blocker._res and blocker._proc:
            break
        time.sleep(1)
    # the refresh may still be recompiling; give it a beat to swap in
    time.sleep(2)

    fails = []

    def check(ok, label, detail=""):
        print("%s  %s%s" % ("PASS" if ok else "FAIL", label,
                            ("  — " + detail) if detail else ""))
        if not ok:
            fails.append(label)

    eng = blocker._engine
    check(eng is not None, "adblock-rust engine available")
    if eng is None:
        return 1

    import adblock                                          # noqa: E402
    probe = eng.url_cosmetic_resources("https://example.com/")
    modern = hasattr(probe, "procedural_actions")
    print("\nengine: adblock %s, resource source %r, procedural_actions %s"
          % (adblock.__version__, blocker._resource_source()[0],
             "LIVE (top's fork)" if modern else "absent (book's 0.6.0)"))
    check(hasattr(probe, "style_selectors") == (not modern),
          "style_selectors present iff legacy engine",
          "gone at 0.12.5, where :style() is a procedural action instead")

    # 1. scriptlets ----------------------------------------------------------
    print("\n-- scriptlets (injected_script) --")
    for url in ("https://www.youtube.com/watch?v=aaaaaaaaaaa",
                "https://www.cnn.com/",
                "https://www.twitch.tv/somechannel"):
        n = len(eng.url_cosmetic_resources(url).injected_script or "")
        check(n > 0, "injected_script non-empty for %s" % url, "%d bytes" % n)
    check(len(blocker._res) > 50, "resource library loaded",
          "%d resources" % len(blocker._res))

    # 2. 4chan's self-hosted ads --------------------------------------------
    print("\n-- 4chan /adv/ (EasyList allow-lists these) --")
    blocked = [
        ("https://www.4chan.org/adv/adv.php", "https://boards.4chan.org/g/", "sub_frame"),
        ("https://s.4cdn.org/adv/vid/ad.mp4", "https://boards.4chan.org/g/", "media"),
        ("https://boards.4chan.org/adv/banner.jpg", "https://boards.4chan.org/g/", "image"),
    ]
    allowed = [
        ("https://i.4cdn.org/g/1234567890.jpg", "https://boards.4chan.org/g/", "image"),
        ("https://s.4cdn.org/css/yotsubluenew.692.css", "https://boards.4chan.org/g/", "stylesheet"),
        ("https://s.4cdn.org/js/core.min.js", "https://boards.4chan.org/g/", "script"),
        ("https://s.4cdn.org/image/fp/logo-transparent.png", "https://boards.4chan.org/g/", "image"),
    ]
    for url, fp, kind in blocked:
        r = eng.check_network_urls(url, fp, kind)
        check(r.matched and not r.exception, "BLOCK  " + url, str(r.filter))
    for url, fp, kind in allowed:
        r = eng.check_network_urls(url, fp, kind)
        check(not (r.matched and not r.exception), "allow  " + url, str(r.filter))

    # 3. generic cosmetic filtering not globally disabled --------------------
    print("\n-- generic cosmetic filtering --")
    for url in ("https://boards.4chan.org/g/", "https://www.cnn.com/"):
        r = eng.url_cosmetic_resources(url)
        check(not r.generichide and len(r.hide_selectors) > 100,
              "generic hiding live for %s" % url,
              "%d selectors, generichide=%s" % (len(r.hide_selectors), r.generichide))

    # 4. procedural filters --------------------------------------------------
    print("\n-- procedural filters --")
    check(blocker._proc_n > 100, "pre-scan index built (book's fallback)",
          "%d rules over %d domains" % (blocker._proc_n, len(blocker._proc)))

    if modern:
        # The engine supplies these; the pre-scan must NOT also fire, or every
        # rule would be applied twice.
        seen = 0
        for url in ("https://www.cnn.com/", "https://boards.4chan.org/g/",
                    "https://www.youtube.com/watch?v=x", "https://www.chip.de/"):
            raw = json.loads(cosmetic.proceduralJson(url))
            seen += len(raw)
            for entry in raw:
                d = json.loads(entry)
                assert isinstance(d.get("selector"), list), d
                for op in d["selector"]:
                    assert "type" in op, op
        check(seen > 0, "proceduralJson returns engine actions",
              "%d across 4 sites" % seen)
        # a :style() rule reaches us ONLY through the procedural path now
        styled = [json.loads(e) for u in ("https://www.cnn.com/", "https://www.chip.de/")
                  for e in json.loads(cosmetic.proceduralJson(u))]
        kinds = sorted({(d.get("action") or {}).get("type", "hide") for d in styled})
        check(bool(styled), "procedural actions carry their action types", ", ".join(kinds))
        css = cosmetic.specificCss("https://www.chip.de/")
        check(":has(" in css, "engine puts :has() straight into hide_selectors",
              "%d bytes of CSS" % len(css))
    else:
        hit = next((d for d in blocker._proc if d.count(".") == 1), None)
        if hit:
            sels = blocker.procedural_selectors("www." + hit)
            check(bool(sels), "pre-scan selectors resolve for www.%s" % hit,
                  "%d, e.g. %s" % (len(sels), sels[0][:60]))
            css = cosmetic.specificCss("https://www.%s/" % hit)
            plain = next((s for s in sels if '"' not in s and "\\" not in s), None)
            check(bool(plain) and plain in css,
                  "specificCss carries the pre-scanned selector", (plain or "")[:60])
        check(json.loads(cosmetic.proceduralJson("https://www.cnn.com/")) == [],
              "proceduralJson is empty on a legacy engine (CSS path already used)")

    # the two slots the injector calls must never raise
    for url in ("https://www.cnn.com/", "https://www.youtube.com/watch?v=x"):
        check(isinstance(cosmetic.specificCss(url), str)
              and isinstance(cosmetic.proceduralJson(url), str)
              and isinstance(cosmetic.specificJs(url), str),
              "injector slots return strings for %s" % url)

    print("\n%s (%d failures)" % ("ALL PASS" if not fails else "FAILURES", len(fails)))
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
