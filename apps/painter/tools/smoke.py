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
import signal
import sys
import time
import urllib.request
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
import userprefs as UP  # noqa: E402

try:
    import boorutags as BT          # the vocabulary, for the tag report below
except ImportError:                 # a checkout without pylib on the path
    BT = None

OUT_DIR = os.path.expanduser("~/Pictures/painter/out")
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov"}

#: Where each node of the graph sits on a 0..1 bar, and what to call it. Only
#: the roles worth naming — anything else lands on a small default, since a bar
#: that jumps backwards is worse than one that pauses.
NODE_FRAC = {"loader": 0.04, "clip": 0.06, "vae": 0.07, "encode_pos": 0.08,
             "encode_neg": 0.09, "load_image": 0.05, "scale_image": 0.06,
             "sampler": 0.10, "decode": 0.88, "create_video": 0.94,
             "save": 0.97}
NODE_LABEL = {"loader": "loading the model", "clip": "loading the encoder",
              "vae": "loading the VAE", "encode_pos": "reading the prompt",
              "encode_neg": "reading the negative",
              "load_image": "reading the picture",
              "scale_image": "sizing the picture", "sampler": "sampling",
              "decode": "decoding", "create_video": "encoding the video",
              "save": "saving"}


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
    ap.add_argument("--seed", type=int,
                    help="fixed seed. Default: whatever his painter settings "
                         "imply (random, reuse, or the one in the box)")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--aspect", help="W:H — sized against --megapixels")
    ap.add_argument("--megapixels", type=float,
                    help="pixel budget: the frame for t2i/t2v, the output size "
                         "for an edit")
    ap.add_argument("--batch", type=int)
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
    ap.add_argument("--progress", action="store_true",
                    help="also print machine-readable `::progress FRAC LABEL` "
                         "and a final `::result JSON` line, for a caller "
                         "drawing this somewhere else")
    ap.add_argument("--no-negpip-fold", dest="fold", action="store_false",
                    default=True,
                    help="keep the negative in its own box even on a NegPip "
                         "family (by default it is folded into the positive)")
    ap.add_argument("--no-prefs", dest="prefs", action="store_false", default=True,
                    help="ignore what he last set in painter for this model")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the graph and print the plan; submit nothing "
                         "(and upload nothing — an --image is taken by name)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    dest="sets",
                    help="ANY other graph param, by its own name — "
                         "`--set shift=3.0`, repeatable. The value is read as "
                         "JSON when it parses (number, true/false, a list) and "
                         "as a string otherwise. This is the escape hatch for a "
                         "knob that has no flag of its own: chatter's "
                         "make_image/make_video pass their `extra` object "
                         "through here, so an agent can reach a param this CLI "
                         "has never heard of.")
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

    # A SIGNAL STOPS THE RENDER ON THE BACKEND, not just this process. Killing
    # the script leaves ComfyUI sampling — nothing on the server knows the
    # caller has gone, and the GPU stays busy for the rest of the job. chatter's
    # Stop button terminates exactly this process (apps/oracle/main.py, cancel),
    # so this handler is what makes that button mean anything [his, 2026-08-24].
    if client is not None:
        def _bail(_sig, _frm):
            # Blocking urllib, not the client's own QNetworkAccessManager: its
            # POSTs are asynchronous, and nothing in a signal handler that ends
            # in `_exit` gets the event loop back to send them.
            def post(path, payload):
                try:
                    urllib.request.urlopen(urllib.request.Request(
                        args.url.rstrip("/") + path,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"}),
                        timeout=5).read()
                except Exception:  # noqa: BLE001 — we are on our way out
                    pass
            ours = [pid for pid in (getattr(client, "_jobs", None) or {})]
            if ours:
                post("/queue", {"delete": ours})
            post("/interrupt", {})
            os._exit(130)
        for _s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(_s, _bail)
    def ref_of(path):
        return os.path.basename(path) if args.dry_run else upload(app, client, path)
    refs = [ref_of(p) for p in args.image]
    last_ref = ref_of(args.last_frame) if args.last_frame else ""

    # HIS OWN SETTINGS ARE THE FLOOR (userprefs.py). painter remembers a whole
    # block per model — steps, cfg, sampler, the negative prompt, the
    # resolution, the clip length — and a generation started from anywhere else
    # should land on the same picture pressing generate would have. Everything
    # named on this command line is laid OVER it, so a caller only has to say
    # what differs.
    kind = "edit" if edit else ("video" if video else "image")
    saved = UP.params_for(entry.name, kind) if args.prefs else {}
    if args.prefs and not args.lora:
        loras = UP.loras_for(reg, entry)
    params = dict(saved)
    params.update({"positive": args.prompt, "loras": loras})
    if args.negative:
        params["negative"] = args.negative
    elif kind != "edit":
        params.setdefault("negative", "")
    seed = args.seed if args.seed is not None else UP.seed_for(
        UP.saved_for(entry.name) if args.prefs else {})
    params["seed"] = 12345 if seed is None else int(seed)
    if args.batch is not None:
        params["batch_size"] = args.batch
    params.setdefault("batch_size", 1)
    for key, val in (("steps", args.steps), ("cfg", args.cfg),
                     ("sampler_name", args.sampler), ("scheduler", args.scheduler),
                     ("denoise", args.denoise),
                     ("width", args.width), ("height", args.height)):
        if val is not None:
            params[key] = val

    # ...and anything else, by name. LAST, so an explicit `--set` beats both the
    # flags above and his saved prefs — it is the most specific thing said.
    for spec in args.sets:
        key, _, raw = spec.partition("=")
        key = key.strip()
        if not key:
            continue
        try:
            params[key] = json.loads(raw)
        except ValueError:
            params[key] = raw

    # SIZE. An aspect plus a pixel budget is what he types; width/height is what
    # the graph takes. The conversion is the registry's own (`calc_dims`), on the
    # family's rounding, so a shorthand "2:3 x1" and painter's own sliders land
    # on the same numbers. Neither applies to an edit (the dropped image sizes
    # it) or to a video with a frame in hand (same rule).
    res = fam.get("resolution") or {}
    mp = args.megapixels
    if not edit and not (video and (refs or last_ref)):
        if not args.width and not args.height and (args.aspect or mp):
            # An aspect or a budget named here REPLACES the remembered
            # width/height — he asked for this shape, not the last one.
            w, h = R.calc_dims(args.aspect or res.get("aspect", "1:1"),
                               mp or params.get("megapixels")
                               or res.get("megapixels", 1.0),
                               res.get("multiple", 32 if video else 64))
            params["width"], params["height"] = w, h
    if mp:
        params["megapixels"] = mp
    if args.seconds is not None:
        params["duration"] = args.seconds
    if args.fps is not None:
        params["fps"] = args.fps

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
        params.setdefault("filename_prefix", "video/painter")
    elif refs:
        raise SystemExit(f"{fam.get('label', entry.family)} takes no input image "
                         "— use --edit, or a video model")

    toggles = dict(params.get("toggles") or {})
    if args.negpip is not None:
        toggles["negpip"] = args.negpip
    if args.ms is not None:
        toggles["model_sampling"] = args.ms
    if toggles:
        params["toggles"] = toggles

    # NEGPIP: THE NEGATIVE GOES IN THE POSITIVE, and the negative box is left
    # empty [his, 2026-08-24]. `CLIPNegPip` is what makes a NEGATIVE WEIGHT work
    # inside the positive prompt — `(lowres, low quality:-1.0)` pushes those
    # away — and on a family that has it on, that is the stronger control: it
    # rides the same patched CLIP the positive does, while the negative box is
    # encoded through the RAW one. So the caller writes a prompt and a negative
    # like anywhere else and this does the spelling, rather than every caller
    # having to remember the syntax (and the sign — a POSITIVE weight there
    # emphasises the very thing it was meant to remove).
    #
    # Only when the toggle is actually on for this run, only when there is a
    # negative to move, and never for a family without the node.
    fold_w = float((fam.get("negpip") or {}).get("weight", -1.0)
                   if isinstance(fam.get("negpip"), dict) else -1.0)
    negpip_on = bool((toggles or fam.get("toggles") or {}).get("negpip"))
    folded = False
    neg = str(params.get("negative") or "").strip()
    if args.fold and negpip_on and neg and not edit and not video:
        params["positive"] = ("%s, (%s:%s)"
                              % (str(params.get("positive") or "").strip().rstrip(","),
                                 neg.strip().rstrip(","), ("%g" % fold_w))).lstrip(", ")
        params["negative"] = ""
        folded = True

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
    print(f"mode     {kind}"
          + ("" if args.prefs else "  (his painter settings ignored)"))
    print(f"model    {entry.name}  [{entry.family}, {entry.loader or 'checkpoint'}]")
    print(f"encoder  {getattr(pairing['encoder'], 'name', '(bundled)')}")
    print(f"vae      {getattr(pairing['vae'], 'name', '(bundled)')}")
    p = built["params"]
    # A dropped frame or an edit subject DECIDES the size, so a width/height
    # left in the params from his saved settings is not what will be rendered.
    by_image = edit or (video and (refs or last_ref))
    size = ("sized by the input image" if by_image
            else (f"{p['width']}x{p['height']}"
                  if p.get("width") and p.get("height") else "family default"))
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
    if folded:
        print(f"negpip   the negative is inline at {fold_w:g}, its own box empty")

    if args.dump_graph:
        with open(args.dump_graph, "w", encoding="utf-8") as fh:
            json.dump(built["prompt"], fh, indent=1, sort_keys=True)
        print(f"graph    -> {args.dump_graph}")

    if args.dry_run:
        return 0

    client.logged.connect(lambda m: print(f"[ws] {m}"))

    # MACHINE-READABLE PROGRESS, for a caller drawing this somewhere else —
    # chatter puts it under the tool disclosure as a bar, because a render is
    # minutes long and a chat with nothing moving in it reads as stalled. One
    # line, `::progress FRAC LABEL`, flushed as it happens: a fraction the
    # caller can draw without knowing anything about samplers, and a label that
    # says which part of the graph is running. The prose lines below stay
    # exactly as they were for a person watching the terminal.
    # MONOTONIC, always. ComfyUI reports a `0/1 … 1/1` for EVERY node, not just
    # the sampler, and it does not walk the graph in the order the bar is drawn
    # in — so an unguarded mapping runs backwards several times a render, which
    # reads worse than no bar at all. The high-water mark is the whole fix.
    seen_frac = [0.0]
    seen_last = [None]

    def emit(frac, label):
        if not args.progress:
            return
        frac = max(0.0, min(1.0, frac))
        if frac < seen_frac[0]:
            frac = seen_frac[0]
        # The socket repeats a step, and a node that reports `0/1 … 1/1` after
        # the sampler has finished contributes nothing but noise on the pipe.
        if seen_last[0] == (frac, label):
            return
        seen_frac[0] = frac
        seen_last[0] = (frac, label)
        print("::progress %.4f %s" % (frac, label), flush=True)

    role_now = [""]

    def on_node(_j, role):
        print(f"  .. {role}")
        role_now[0] = role
        # Sampling is nearly all of the wall clock, so the stages around it get
        # the ends of the bar rather than an equal share of it.
        emit(NODE_FRAC.get(role, 0.05), NODE_LABEL.get(role, role))

    client.jobNode.connect(on_node)

    last = [0.0]

    def on_prog(_job, value, maximum):
        now = time.time()
        if maximum and (now - last[0] > 1.0 or value >= maximum):
            last[0] = now
            print(f"  {value}/{maximum}")
        # Only the SAMPLER's steps move the bar: every other node's progress is
        # a one-tick `0/1 … 1/1` that says nothing about the wait.
        if maximum and role_now[0] == "sampler":
            # The sampler owns 10%..85% of the bar; the rest is load and decode.
            emit(0.10 + 0.75 * (float(value) / float(maximum)),
                 "sampling %d/%d" % (value, maximum))

    client.jobProgress.connect(on_prog)
    emit(0.02, "loading the model")

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
    if args.progress:
        # WHAT MADE IT, for the caption the caller writes. Read off the built
        # params rather than the command line, so it is what the graph actually
        # ran with — including everything that came from his painter settings
        # and never appeared as a flag.
        emit(1.0, "done")
        print("::result " + json.dumps({
            # The prompt the GRAPH ran, not the one it was handed: transformed,
            # and with the negative folded in where NegPip took it. That is what
            # the caption in the chat should say [his, 2026-08-24 — "i dont see
            # the negpip negative text anywhere in the caption of that image"].
            "positive": p.get("positive", ""),
            "negative": p.get("negative", ""),
            "model": entry.name, "kind": kind, "seed": p.get("seed"),
            "steps": p.get("steps"), "cfg": p.get("cfg"),
            "sampler": p.get("sampler_name"), "scheduler": p.get("scheduler"),
            "width": p.get("width"), "height": p.get("height"),
            "frames": p.get("frames"), "fps": p.get("fps"),
            "sized_by_image": bool(by_image),
            # WHICH TAGS DID NOTHING. A caller that cannot see the picture has
            # no other way to learn that half its prompt was invented — on
            # 2026-08-24 a model wrote `lain igarashi`, which is not the
            # character, and nothing anywhere said so. Only for families
            # prompted in Danbooru tags; `check` judges only the pieces that
            # look like tags (apps/pylib/boorutags.py).
            "tags": (BT.check(p.get("positive", ""))
                     if (BT is not None
                         and fam.get("prompt_transform") == "danbooru") else None),
            "seconds": round(float(p["frames"]) / float(p["fps"]), 2)
                       if p.get("frames") and p.get("fps") else None,
            "files": saved}), flush=True)
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
