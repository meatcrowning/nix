#!/usr/bin/env python3
"""Run every base model once, to prove the backend really can load all of them.

One step at a small resolution: this is a "does it load and decode" check, not a
quality check.  It is the gate that has to pass before the UI is worth building,
because it covers the awkward cases -- the int8 loader, three GGUFs, the two
bundled checkpoints, and the pixel-space model that needs the stub VAE.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore  # noqa: E402

import comfy as C  # noqa: E402
import graph as G  # noqa: E402
import registry as R  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=C.DEFAULT_URL)
    ap.add_argument("--steps", type=int, default=1)
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--only", help="substring filter on model name")
    ap.add_argument("--report", default="/tmp/painter-coverage.json")
    ap.add_argument("--free-between", action="store_true", default=True,
                    help="unload models between runs to avoid VRAM pileup")
    args = ap.parse_args(argv)

    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    reg = R.Registry()
    try:
        oi = G.fetch_object_info(args.url)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"backend unreachable: {exc}")

    models = [e for e in reg.base_models()
              if not args.only or args.only.lower() in e.name.lower()]
    print(f"testing {len(models)} models at {args.size}x{args.size}, {args.steps} step\n")

    client = C.ComfyClient(args.url)
    results = []
    for i, entry in enumerate(models, 1):
        label = f"[{i}/{len(models)}] {entry.name}"
        rec = {"name": entry.name, "family": entry.family,
               "loader": entry.loader or "CheckpointLoaderSimple", "quant": entry.quant}
        try:
            built = reg.build(entry, {
                "positive": "a red cube", "negative": "", "seed": 1,
                "steps": args.steps, "width": args.size, "height": args.size,
                "filename_prefix": "painter_cov",
            }, object_info=oi)
        except (G.GraphError, G.ValidationError) as exc:
            rec.update(ok=False, error=f"build: {exc}")
            results.append(rec)
            print(f"{label}\n    BUILD FAILED: {exc}\n")
            continue

        t0 = time.time()
        jobs = C.run_jobs(client, lambda c, b=built: [c.submit(b["prompt"], b["params"])],
                          timeout=args.timeout)
        job = jobs[0]
        rec["seconds"] = round(time.time() - t0, 1)
        if job.error:
            rec.update(ok=False, error=job.error)
            print(f"{label}\n    FAILED ({rec['seconds']}s): {job.error}\n")
        else:
            rec.update(ok=True, images=[im["filename"] for im in job.images])
            print(f"{label}\n    ok  {rec['seconds']}s  -> {rec['images']}\n")
        results.append(rec)

        if args.free_between:
            client.free(unload_models=True)
            for _ in range(20):
                app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)

    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)

    print("=" * 68)
    print(f"{len(ok)}/{len(results)} models ran")
    for r in bad:
        print(f"  FAILED  {r['name']:<52} {r.get('error', '')[:120]}")
    print(f"report: {args.report}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
