#!/usr/bin/env python3
"""Generate through painter's own registry/graph/client, with no GUI involved.

This is the end-to-end path the UI uses, minus QML, so a failure here is a
failure in painter proper rather than in the interface.

It is also chatter's generator: `make_image`/`make_video` shell out to this
(apps/oracle/main.py), which is why every mode painter has — text-to-image,
edit, image-to-video — is reachable here as flags rather than only from the
window. Nothing about a model lives in this file; it picks an entry out of the
registry and hands `registry.build()` the same params dict the UI does.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PAINTER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PAINTER)
sys.path.insert(0, os.path.join(os.path.dirname(PAINTER), "pylib"))  # pngmeta lives here

from PySide6 import QtCore  # noqa: E402

import comfy as C  # noqa: E402
import graph as G  # noqa: E402
import mp4meta  # noqa: E402
import pngmeta  # noqa: E402
import registry as R  # noqa: E402

OUT_DIR = os.path.expanduser("~/Pictures/painter/out")
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov"}


def pick(reg, wanted, mode=""):
    """The model this run generates with.

    A `--mode` is painter's own shortcut (`registry.MODES`: anime/real/edit/
    video) and resolves to HIS canonical file for that mode, so chatter naming
    "anima" or "klein" lands on exactly what the button would have. An explicit
    `--model` still wins — it is the more specific ask.
    """
    if wanted:
        e = reg.find(wanted)
        if e is None:
            matches = [x for x in reg.base_models() if wanted.lower() in x.name.lower()]
            e = matches[0] if matches else None
        if e is None:
            raise SystemExit(f"no model matching {wanted!r}")
        return e
    if mode:
        e = reg.mode_model(mode)
        if e is None:
            raise SystemExit(f"no model here for mode {mode!r}")
        return e
    return reg.base_models()[0]


def pump(app, box, timeout=120.0):
    """Spin the event loop until a callback has filled `box`, or time is up."""
    deadline = time.time() + timeout
    while not box and time.time() < deadline:
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
        QtCore.QThread.msleep(10)
    return bool(box)


def upload(app, client, path):
    """A local file -> the ref a LoadImage node takes.

    It goes over HTTP rather than by path because the backend is not
    necessarily on this filesystem (book reaches top's through the tunnel), and
    because ComfyUI only loads out of its own input directory.
    """
    box = {}
    client.upload_image(os.path.expanduser(path),
                        lambda ref, err: box.update(ref=ref, err=err))
    if not pump(app, box, 120.0):
        raise SystemExit(f"upload timed out: {path}")
    if box.get("err") or not box.get("ref"):
        raise SystemExit(f"upload failed for {path}: {box.get('err')}")
    return box["ref"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=C.DEFAULT_URL)
    ap.add_argument("--model")
    ap.add_argument("--mode", choices=[m["id"] for m in R.MODES],
                    help="painter's own shortcut: anime/real/edit/video")
    ap.add_argument("--prompt", default="a red cube on a white table, studio light")
    ap.add_argument("--negative", default="")
    ap.add_argument("--steps", type=int)
    ap.add_argument("--cfg", type=float)
    ap.add_argument("--sampler")
    ap.add_argument("--scheduler")
    ap.add_argument("--denoise", type=float)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--aspect", help="W:H — sized against --megapixels")
    ap.add_argument("--megapixels", type=float,
                    help="pixel budget: the frame for t2i/t2v, the output size "
                         "for an edit")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--edit", action="store_true",
                    help="edit the --image(s) instead of generating fresh")
    ap.add_argument("--image", action="append", default=[], metavar="PATH",
                    help="input image: the edit subject, or a video's FIRST "
                         "frame. Repeatable (edit references).")
    ap.add_argument("--last-frame", dest="last_frame", metavar="PATH",
                    help="a video's last frame")
    ap.add_argument("--seconds", type=float, help="video duration")
    ap.add_argument("--fps", type=float)
    ap.add_argument("--lora", action="append", default=[],
                    help="NAME[:STRENGTH], repeatable")
    ap.add_argument("--negpip", dest="negpip", action="store_true", default=None)
    ap.add_argument("--no-negpip", dest="negpip", action="store_false")
    ap.add_argument("--model-sampling", dest="ms", action="store_true", default=None)
    ap.add_argument("--no-model-sampling", dest="ms", action="store_false")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--dump-graph", metavar="PATH")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the graph and print the plan; submit nothing "
                         "(and upload nothing — an --image is taken by name)")
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args(argv)

    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    reg = R.Registry()
    edit = bool(args.edit) or (args.mode == "edit")
    entry = pick(reg, args.model, args.mode or ("edit" if edit else ""))
    fam = reg.family_of(entry) or {}
    video = fam.get("kind") == "video"

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

    if edit and not args.image:
        raise SystemExit("--edit needs at least one --image")
    if edit and not (fam.get("edit")):
        raise SystemExit(f"{fam.get('label', entry.family)} cannot edit an image")

    client = None if args.dry_run else C.ComfyClient(args.url)
    def ref_of(path):
        return os.path.basename(path) if args.dry_run else upload(app, client, path)
    refs = [ref_of(p) for p in args.image]
    last_ref = ref_of(args.last_frame) if args.last_frame else ""

    params = {"positive": args.prompt, "negative": args.negative, "seed": args.seed,
              "batch_size": args.batch, "loras": loras}
    for key, val in (("steps", args.steps), ("cfg", args.cfg),
                     ("sampler_name", args.sampler), ("scheduler", args.scheduler),
                     ("denoise", args.denoise),
                     ("width", args.width), ("height", args.height)):
        if val is not None:
            params[key] = val

    # SIZE. An aspect plus a pixel budget is what he types; width/height is what
    # the graph takes. The conversion is the registry's own (`calc_dims`), on the
    # family's rounding, so a shorthand "2:3 x1" and painter's own sliders land
    # on the same numbers. Neither applies to an edit (the dropped image sizes
    # it) or to a video with a frame in hand (same rule).
    res = fam.get("resolution") or {}
    mp = args.megapixels
    if not edit and not (video and (refs or last_ref)):
        if not args.width and not args.height and (args.aspect or mp):
            w, h = R.calc_dims(args.aspect or res.get("aspect", "1:1"),
                               mp or res.get("megapixels", 1.0),
                               res.get("multiple", 32 if video else 64))
            params["width"], params["height"] = w, h
    if mp:
        params["megapixels"] = mp

    if edit:
        params["edit"] = True
        params["input_images"] = refs
        params["input_image"] = refs[0]
        # A megapixel budget given by hand means RESIZE to it; given none, the
        # edit keeps the original's exact pixels (painter's own default).
        params["editNoScale"] = mp is None
        if mp is not None:
            params["editMegapixels"] = mp
    elif video:
        if refs:
            params["use_input_image"] = True
            params["input_image"] = refs[0]
        if last_ref:
            params["use_last_frame"] = True
            params["last_image"] = last_ref
        if args.seconds is not None:
            params["duration"] = args.seconds
        if args.fps is not None:
            params["fps"] = args.fps
        params.setdefault("filename_prefix", "video/painter")
    elif refs:
        raise SystemExit(f"{fam.get('label', entry.family)} takes no input image "
                         "— use --edit, or a video model")

    toggles = {}
    if args.negpip is not None:
        toggles["negpip"] = args.negpip
    if args.ms is not None:
        toggles["model_sampling"] = args.ms
    if toggles:
        params["toggles"] = toggles

    oi = None
    if not args.dry_run:
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
    kind = "edit" if edit else ("video" if video else "image")
    print(f"mode     {kind}")
    print(f"model    {entry.name}  [{entry.family}, {entry.loader or 'checkpoint'}]")
    print(f"encoder  {getattr(pairing['encoder'], 'name', '(bundled)')}")
    print(f"vae      {getattr(pairing['vae'], 'name', '(bundled)')}")
    p = built["params"]
    size = (f"{p['width']}x{p['height']}" if p.get("width") and p.get("height")
            else "sized by the input image")
    print(f"sampling {p.get('steps')} steps, cfg {p.get('cfg')}, "
          f"{p.get('sampler_name')}/{p.get('scheduler')}, {size}, "
          f"seed {p.get('seed')}")
    if video:
        print(f"clip     {p.get('frames')} frames @ {p.get('fps')} fps"
              + (f", first frame {p.get('input_image')}" if p.get("input_image") else "")
              + (f", last frame {p.get('last_image')}" if p.get("last_image") else ""))
    if edit:
        print(f"editing  {', '.join(p.get('input_images') or [])}")
    print(f"toggles  {p.get('toggles')}  loras={[l['name'] for l in loras]}")

    if args.dump_graph:
        with open(args.dump_graph, "w", encoding="utf-8") as fh:
            json.dump(built["prompt"], fh, indent=1, sort_keys=True)
        print(f"graph    -> {args.dump_graph}")

    if args.dry_run:
        return 0

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

    saved = []
    for img in job.images:
        got = {}

        def cb(data, _g=got):
            _g["data"] = data

        client.download(img, cb)
        deadline = time.time() + 300
        while "data" not in got and time.time() < deadline:
            app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
        data = got.get("data")
        if not data:
            print(f"  could not fetch {img['filename']}", file=sys.stderr)
            continue
        # Both shapes carry the job that made them, in the place their own format
        # keeps text — a PNG in a tEXt chunk, an MP4 as an `mdta` tag. A file
        # that cannot take the tag is written verbatim rather than not written.
        described = pngmeta.describe(built["params"], pairing)
        name = str(img["filename"])
        try:
            if name.lower().endswith(".png"):
                data = pngmeta.upsert_text(data, described)
            elif Path(name).suffix.lower() in VIDEO_SUFFIXES:
                data = mp4meta.upsert_tags(data, described)
        except Exception:  # noqa: BLE001 — metadata is never worth losing output
            pass
        dest = Path(args.out_dir) / (img.get("subfolder") or "") / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        saved.append(str(dest))

    print(f"\nprompt_id {job.prompt_id}  in {job.duration:.1f}s")
    for s in saved:
        print(f"  saved {s} ({os.path.getsize(s)} bytes)")
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
