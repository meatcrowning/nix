#!/usr/bin/env python3
"""Generate through painter's own registry/graph/client, with no GUI involved.

This is the end-to-end path the UI uses, minus QML, so a failure here is a
failure in painter proper rather than in the interface.
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
import pngmeta  # noqa: E402
import registry as R  # noqa: E402

OUT_DIR = os.path.expanduser("~/Pictures/painter/out")


def pick(reg, wanted):
    if wanted:
        e = reg.find(wanted)
        if e is None:
            matches = [x for x in reg.base_models() if wanted.lower() in x.name.lower()]
            e = matches[0] if matches else None
        if e is None:
            raise SystemExit(f"no model matching {wanted!r}")
        return e
    return reg.base_models()[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=C.DEFAULT_URL)
    ap.add_argument("--model")
    ap.add_argument("--prompt", default="a red cube on a white table, studio light")
    ap.add_argument("--negative", default="")
    ap.add_argument("--steps", type=int)
    ap.add_argument("--cfg", type=float)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--lora", action="append", default=[],
                    help="NAME[:STRENGTH], repeatable")
    ap.add_argument("--negpip", dest="negpip", action="store_true", default=None)
    ap.add_argument("--no-negpip", dest="negpip", action="store_false")
    ap.add_argument("--model-sampling", dest="ms", action="store_true", default=None)
    ap.add_argument("--no-model-sampling", dest="ms", action="store_false")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--dump-graph", metavar="PATH")
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args(argv)

    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    reg = R.Registry()
    entry = pick(reg, args.model)

    loras = []
    for spec in args.lora:
        name, _, strength = spec.partition(":")
        e = reg.find(name) or next(
            (x for x in reg.loras() if name.lower() in x.name.lower()), None
        )
        if e is None:
            raise SystemExit(f"no LoRA matching {name!r}")
        verdict = reg.lora_compat(e, entry)
        if not verdict["ok"]:
            print(f"warning: {e.name} looks incompatible - {verdict['reason']}",
                  file=sys.stderr)
        loras.append({"name": e.name, "strength": float(strength or 1.0),
                      "patches_clip": e.patches_clip})

    params = {"positive": args.prompt, "negative": args.negative, "seed": args.seed,
              "batch_size": args.batch, "loras": loras}
    for key, val in (("steps", args.steps), ("cfg", args.cfg),
                     ("width", args.width), ("height", args.height)):
        if val is not None:
            params[key] = val
    toggles = {}
    if args.negpip is not None:
        toggles["negpip"] = args.negpip
    if args.ms is not None:
        toggles["model_sampling"] = args.ms
    if toggles:
        params["toggles"] = toggles

    try:
        oi = G.fetch_object_info(args.url)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"backend unreachable at {args.url}: {exc}")

    try:
        built = reg.build(entry, params, object_info=oi)
    except G.ValidationError as exc:
        print("graph rejected before submit:", file=sys.stderr)
        for p in exc.problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    except G.GraphError as exc:
        raise SystemExit(f"cannot build: {exc}")

    pairing = built["pairing"]
    print(f"model    {entry.name}  [{entry.family}, {entry.loader or 'checkpoint'}]")
    print(f"encoder  {getattr(pairing['encoder'], 'name', '(bundled)')}")
    print(f"vae      {getattr(pairing['vae'], 'name', '(bundled)')}")
    p = built["params"]
    print(f"sampling {p['steps']} steps, cfg {p['cfg']}, {p['sampler_name']}/"
          f"{p['scheduler']}, {p['width']}x{p['height']}, seed {p['seed']}")
    print(f"toggles  {p['toggles']}  loras={[l['name'] for l in loras]}")

    if args.dump_graph:
        with open(args.dump_graph, "w", encoding="utf-8") as fh:
            json.dump(built["prompt"], fh, indent=1, sort_keys=True)
        print(f"graph    -> {args.dump_graph}")

    client = C.ComfyClient(args.url)
    client.logged.connect(lambda m: print(f"[ws] {m}"))
    client.jobNode.connect(lambda _j, role: print(f"  .. {role}"))

    last = [0.0]

    def on_prog(_job, value, maximum):
        now = time.time()
        if maximum and (now - last[0] > 1.0 or value >= maximum):
            last[0] = now
            print(f"  {value}/{maximum}")

    client.jobProgress.connect(on_prog)

    jobs = C.run_jobs(client, lambda c: [c.submit(built["prompt"], built["params"])],
                      timeout=args.timeout)
    job = jobs[0]
    if job.error:
        print(f"\nFAILED: {job.error}", file=sys.stderr)
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    saved = []
    for img in job.images:
        got = {}

        def cb(data, _g=got):
            _g["data"] = data

        client.download(img, cb)
        deadline = time.time() + 60
        while "data" not in got and time.time() < deadline:
            app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
        data = got.get("data")
        if not data:
            print(f"  could not fetch {img['filename']}", file=sys.stderr)
            continue
        try:
            data = pngmeta.upsert_text(data, pngmeta.describe(built["params"], pairing))
        except ValueError:
            pass
        dest = os.path.join(args.out_dir, img["filename"])
        with open(dest, "wb") as fh:
            fh.write(data)
        saved.append(dest)

    print(f"\nprompt_id {job.prompt_id}  in {job.duration:.1f}s")
    for s in saved:
        print(f"  saved {s} ({os.path.getsize(s)} bytes)")
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
