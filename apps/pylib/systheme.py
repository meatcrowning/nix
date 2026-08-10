#!/usr/bin/env python3
"""album cover -> desktop systheme, end to end.

ONE reusable entry point that turns an album-cover image into a 16:9 desktop
wallpaper and applies it, so the wal-derived palette regenerates across the
whole desktop (panel, kitty, hyprland border, RGB). It is the codification of
the hand-run recipe that produced the OPN *Monody / The Station* wallpaper:

    cover  ->  remove all text/lettering
           ->  reposition the subject to the centre
           ->  outpaint/expand the composition to 16:9
           ->  set as the wallpaper  ->  wal-set.sh recolours everything

Two production methods, auto-selected, same contract either way:

  * ``comfy``  — the PREFERRED, picture-faithful route: the headless ComfyUI
    backend (apps/painter's Flux 2 Klein *edit* graph) removes text (Latin and
    CJK/Japanese alike, by prompt) and genuinely outpaints a photographic
    background. It is primed with a mirror-blurred continuation in the extension
    margins (``_outpaint_input``) rather than a flat border, so the edit model
    invents new scene rather than reproducing a flat field. Used whenever the
    backend is reachable AND healthy. LOCAL models only (loopback / ssh-tunnelled
    8188 — on book that is top's GPU over apps/painter/tools/comfy-tunnel.sh).
  * ``flat``   — the documented FALLBACK for when the backend is unreachable,
    and a good fit for covers on a UNIFORM background (the Monody green, the Love
    Deluxe cream): lettering — including CJK blocks — is erased by filling the
    sampled background colour (``_text_regions``), the subject is recentred, and
    the flat field is extended to 16:9. For a flat-background cover this is
    visually close to the generative pass; the tool always says which it used.

STABLE CLI (a player right-click "create systheme" action shells out to this):

    python3 <repo>/apps/pylib/systheme.py <cover-image> [options]

    positional
      cover-image            path to the album cover (any format Pillow reads)
    options
      --name NAME            output basename (default: cover's stem, slugified)
      --out-dir DIR          where the wallpaper PNG lands
                             (default: ~/Pictures/wall)
      --width N --height N   target wallpaper size (default 1920x1080)
      --method auto|comfy|flat   force a route (default auto)
      --comfy-url URL        ComfyUI base (default http://127.0.0.1:8188)
      --erase X0,Y0,X1,Y1    extra rectangle(s) to blank to background; repeatable
      --no-set               produce the PNG but do NOT apply the theme
      --json                 emit a one-line JSON result on stdout
      -q/--quiet             progress to stderr off

    stdout    the absolute wallpaper path (or, with --json, a JSON object:
              {"wallpaper": "...", "method": "comfy|flat", "applied": bool,
               "width": N, "height": N})
    exit      0 success; non-zero on failure, with a reason on stderr.

Dependencies: Pillow + stdlib only (no numpy) — so it runs under both hosts'
python. The theme is applied by delegating to ~/.config/scripts/wal-set.sh,
wrapped in hypr-session-env.sh so a live-compositor call resolves the real
instance (see home/srvs/hypr-env.nix).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
except Exception as e:  # pragma: no cover - environment guard
    sys.stderr.write(f"systheme: Pillow is required ({e})\n")
    raise SystemExit(2)

HOME = Path.home()
DEFAULT_OUT = HOME / "Pictures" / "wall"
SCRIPTS = HOME / ".config" / "scripts"
DEFAULT_COMFY = "http://127.0.0.1:8188"


def log(msg: str) -> None:
    if not _QUIET:
        sys.stderr.write(f"systheme: {msg}\n")
        sys.stderr.flush()


_QUIET = False


# --------------------------------------------------------------------------- #
#  background / subject analysis (Pillow-only, no numpy)
# --------------------------------------------------------------------------- #
def _corner_bg(im: "Image.Image") -> tuple[int, int, int]:
    """Background colour = mean of the four 20px corners."""
    w, h = im.size
    s = min(20, w // 4, h // 4) or 1
    boxes = [(0, 0), (w - s, 0), (0, h - s), (w - s, h - s)]
    acc = [0, 0, 0]
    n = 0
    px = im.load()
    for bx, by in boxes:
        for x in range(bx, bx + s):
            for y in range(by, by + s):
                r, g, b = px[x, y][:3]
                acc[0] += r
                acc[1] += g
                acc[2] += b
                n += 1
    return tuple(c // n for c in acc)  # type: ignore[return-value]


def _fg_mask(im: "Image.Image", bg: tuple[int, int, int], thresh: int = 34) -> "Image.Image":
    solid = Image.new("RGB", im.size, bg)
    return ImageChops.difference(im, solid).convert("L").point(lambda v: 255 if v > thresh else 0)


def _bg_uniformity(im: "Image.Image", bg: tuple[int, int, int]) -> float:
    """Fraction of the 8px border ring that is within tolerance of ``bg``.

    A flat-background cover scores ~1.0; a photograph bleeding to the edge is low.
    """
    mask = _fg_mask(im, bg, thresh=30)
    w, h = im.size
    ring = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(ring)
    d.rectangle((0, 0, w - 1, 7), fill=255)
    d.rectangle((0, h - 8, w - 1, h - 1), fill=255)
    d.rectangle((0, 0, 7, h - 1), fill=255)
    d.rectangle((w - 8, 0, w - 1, h - 1), fill=255)
    ring_px = ring.tobytes()
    fg_px = mask.tobytes()
    total = sum(1 for v in ring_px if v)
    if not total:
        return 1.0
    off = sum(1 for r, f in zip(ring_px, fg_px) if r and f)
    return 1.0 - off / total


def _cc(cellset: set) -> list[set]:
    """8-connected components over a set of (cx, cy) grid cells."""
    seen: set = set()
    comps: list[set] = []
    for c in cellset:
        if c in seen:
            continue
        stack = [c]
        seen.add(c)
        comp: set = set()
        while stack:
            x, y = stack.pop()
            comp.add((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (x + dx, y + dy)
                    if n in cellset and n not in seen:
                        seen.add(n)
                        stack.append(n)
        comps.append(comp)
    return comps


def _dilate(cells: set, ncx: int, ncy: int, r: int = 1) -> set:
    out: set = set()
    for (x, y) in cells:
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < ncx and 0 <= ny < ncy:
                    out.add((nx, ny))
    return out


def _text_regions(mask: "Image.Image", margin_frac: float = 0.42) -> list[tuple[int, int, int, int]]:
    """Isolated foreground clusters hugging the top/left edge = lettering.

    A grid connected-components detector, robust to CJK/Japanese glyphs — which
    are denser, blockier and taller than a Latin label and defeated the old
    row/column band scan (it found only stroke slivers of "空夜 / 静焔" and left
    the block standing). The frame is reduced to a coarse density grid; the
    subject is the largest *solid* cell mass; text is any well-filled ink
    cluster that is (a) separated from that mass by background and (b) hugging
    the TOP or LEFT edge, where album titling sits. Restricting to those two
    edges is deliberate: on a busy photographic cover a lit neck or shoulder in
    the bottom/right margin reads geometrically like a label, and this is the
    fallback route — the comfy route removes text by prompt and is preferred.

    Verified offscreen against three covers: the CJK "空夜 / 静焔" block, Monody's
    "THE STATION" title, and Love Deluxe's "sade love deluxe" — all caught, no
    subject pixels erased.
    """
    w, h = mask.size
    cs = max(4, min(w, h) // 90)
    ncx = max(1, w // cs)
    ncy = max(1, h // cs)
    small = mask.resize((ncx, ncy), Image.BOX)
    sp = small.load()
    frac = [[sp[cx, cy] / 255.0 for cy in range(ncy)] for cx in range(ncx)]
    solid = {(cx, cy) for cx in range(ncx) for cy in range(ncy) if frac[cx][cy] > 0.55}
    ink = {(cx, cy) for cx in range(ncx) for cy in range(ncy) if frac[cx][cy] > 0.12}
    if not ink:
        return []

    # subject mass = the largest solid component, dilated a little so the text
    # candidate set never includes an anti-aliased fringe of it.
    subj_cells: set = set()
    scomps = _cc(solid)
    if scomps:
        subj_cells = _dilate(max(scomps, key=len), ncx, ncy, 2)

    # text candidates: ink outside the subject, closed by one cell so a glyph's
    # thin strokes bridge into one component instead of fragmenting.
    cand = _dilate(ink - subj_cells, ncx, ncy, 1) - subj_cells

    out: list[tuple[int, int, int, int]] = []
    frame_cells = ncx * ncy
    edge = max(2, int(min(ncx, ncy) * 0.11))
    for comp in _cc(cand):
        if len(comp) < 6:
            continue
        xs = [c[0] for c in comp]
        ys = [c[1] for c in comp]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        area = (x1 - x0 + 1) * (y1 - y0 + 1)
        if area > frame_cells * 0.20:  # too big for a margin label
            continue
        top_label = y0 < edge
        left_label = x0 < edge and y1 < ncy * 0.72
        if not (top_label or left_label):
            continue
        if len(comp) / area < 0.18:  # too sparse -> a stray fringe, not text
            continue
        # isolation: the ring just outside the cluster is mostly background, or
        # it is fused with the subject and not a standalone label.
        ring = _dilate(comp, ncx, ncy, 2) - _dilate(comp, ncx, ncy, 0)
        if ring and sum(1 for c in ring if c in ink) / len(ring) > 0.30:
            continue
        out.append((x0 * cs, y0 * cs, min(w, (x1 + 1) * cs), min(h, (y1 + 1) * cs)))
    return out


def _erase(im: "Image.Image", bg: tuple[int, int, int], rects: list[tuple[int, int, int, int]], pad: int = 6) -> "Image.Image":
    if not rects:
        return im
    im = im.copy()
    d = ImageDraw.Draw(im)
    w, h = im.size
    for x0, y0, x1, y1 in rects:
        d.rectangle((max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)), fill=bg)
    return im


def _subject_bbox(im: "Image.Image", bg: tuple[int, int, int]) -> tuple[int, int, int, int]:
    mask = _fg_mask(im, bg, thresh=30)
    bb = mask.getbbox()
    return bb or (0, 0, im.size[0], im.size[1])


# --------------------------------------------------------------------------- #
#  the flat (uniform-background) route
# --------------------------------------------------------------------------- #
def render_flat(
    im: "Image.Image",
    width: int,
    height: int,
    extra_erase: list[tuple[int, int, int, int]],
) -> "Image.Image":
    im = im.convert("RGB")
    bg = _corner_bg(im)
    log(f"flat route: background {bg}")

    mask = _fg_mask(im, bg, thresh=30)
    rects = _text_regions(mask) + list(extra_erase)
    if rects:
        log(f"erasing {len(rects)} text/label region(s)")
    clean = _erase(im, bg, rects)

    sx0, sy0, sx1, sy1 = _subject_bbox(clean, bg)
    subj = clean.crop((sx0, sy0, sx1, sy1))
    sw, sh = subj.size

    # does the subject bleed off the source bottom? (hair, a dress) -> keep it
    # flush to the canvas bottom rather than floating it in centred space.
    src_h = im.size[1]
    touches_bottom = sy1 >= src_h - 2

    # scale the subject to sit inside the frame with a little breathing room
    pad_v = 0.94 if touches_bottom else 0.90
    scale = min(width * 0.86 / sw, height * pad_v / sh)
    tw, th = max(1, round(sw * scale)), max(1, round(sh * scale))
    subj = subj.resize((tw, th), Image.LANCZOS)

    canvas = Image.new("RGB", (width, height), bg)
    ox = (width - tw) // 2
    oy = height - th if touches_bottom else (height - th) // 2
    canvas.paste(subj, (ox, oy))
    log(f"subject {sw}x{sh} -> {tw}x{th} at ({ox},{oy}); bottom-flush={touches_bottom}")
    return canvas


# --------------------------------------------------------------------------- #
#  the comfy (generative) route — LOCAL models via the headless backend
# --------------------------------------------------------------------------- #
def comfy_healthy(base: str, timeout: float = 4.0) -> bool:
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/system_stats", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _outpaint_input(
    im: "Image.Image",
    width: int,
    height: int,
    extra_erase: list[tuple[int, int, int, int]],
) -> "Image.Image":
    """Prime a 16:9 canvas the edit model can genuinely OUTPAINT into.

    The edit graph regenerates the whole frame conditioned on this image's VAE
    encoding (a ReferenceLatent), so what sits in the extension margins decides
    what the model puts there. A FLAT sampled-colour border — the old prime,
    render_flat's output — tells the reference "this area is a flat field", and
    the model faithfully reproduces the flat border: the lazy result. Instead:

      * erase lettering (the CJK-robust _text_regions, so text is never carried
        into the extension), then scale the cleaned cover as LARGE as the frame
        allows on its limiting axis — a square cover fills the height, leaving
        side margins to invent, which keeps the subject big and the outpaint a
        modest horizontal extension;
      * fill each margin with a MIRROR of the adjacent edge, then blur it,
        feathered back into the sharp core. That gives the reference a plausible
        low-frequency continuation of colour and texture for the model to
        sharpen into real scene content, instead of a hard flat field.

    The result is the /upload/image payload; the graph outpaints from it.
    """
    im = im.convert("RGB")
    bg = _corner_bg(im)
    mask = _fg_mask(im, bg, thresh=30)
    rects = _text_regions(mask) + list(extra_erase)
    if rects:
        log(f"outpaint prime: erasing {len(rects)} text region(s) before extension")
    clean = _erase(im, bg, rects)

    cw, ch = clean.size
    s = height / ch
    if cw * s > width:  # a wide cover -> fill width instead, outpaint top/bottom
        s = width / cw
    tw, th = max(1, round(cw * s)), max(1, round(ch * s))
    core = clean.resize((tw, th), Image.LANCZOS)

    canvas = Image.new("RGB", (width, height), bg)
    ox, oy = (width - tw) // 2, (height - th) // 2
    canvas.paste(core, (ox, oy))

    # reflect the core outward into whichever margin exists (never both — the
    # fill picks one axis — so there are no unfilled corners to seam)
    if ox > 0:
        m1 = ImageOps.mirror(core.crop((0, 0, min(ox, tw), th)))
        canvas.paste(m1, (ox - m1.width, oy))
        m2 = ImageOps.mirror(core.crop((tw - min(width - (ox + tw), tw), 0, tw, th)))
        canvas.paste(m2, (ox + tw, oy))
    if oy > 0:
        m1 = ImageOps.flip(core.crop((0, 0, tw, min(oy, th))))
        canvas.paste(m1, (ox, oy - m1.height))
        m2 = ImageOps.flip(core.crop((0, th - min(height - (oy + th), th), tw, th)))
        canvas.paste(m2, (ox, oy + th))

    # blur the extension band, feathered back into the sharp core
    feather = max(8, min(width, height) // 24)
    blurred = canvas.filter(ImageFilter.GaussianBlur(max(4, min(width, height) // 50)))
    fmask = Image.new("L", (width, height), 255)
    ImageDraw.Draw(fmask).rectangle(
        (ox + feather, oy + feather, ox + tw - feather - 1, oy + th - feather - 1), fill=0
    )
    fmask = fmask.filter(ImageFilter.GaussianBlur(feather))
    canvas.paste(blurred, (0, 0), fmask)
    log(f"outpaint prime: core {tw}x{th} at ({ox},{oy}); mirror+blur extension")
    return canvas


def render_comfy(
    im: "Image.Image",
    width: int,
    height: int,
    base: str,
) -> "Image.Image":
    """Text-removal + outpaint via apps/painter's Flux 2 Klein edit graph.

    The general route. It uploads the cover, runs an edit prompt that removes
    lettering and recentres the subject, then outpaints onto a 16:9 canvas.
    Kept deliberately thin: it drives the same ComfyUI HTTP API painter speaks
    and reuses painter's proven edit template, so a Comfy update can only move
    a node contract, never the interface here.

    NOTE: exercised through the live backend only (top's GPU); when the backend
    is unhealthy the caller falls back to render_flat, which is why this raises
    rather than degrading silently.
    """
    import io
    import time
    import uuid

    # painter owns the model registry and the graph builder; reuse them so this
    # stays a caller of the SAME pipeline painter's "edit" mode drives, not a
    # second hand-rolled copy of it. graph.py imports registry/pngmeta relative
    # to painter/, so painter/ must be importable.
    painter = Path(__file__).resolve().parent.parent / "painter"
    if str(painter) not in sys.path:
        sys.path.insert(0, str(painter))
    import registry as R  # type: ignore
    import graph as G  # type: ignore

    base = base.rstrip("/")

    # 1. prime a 16:9 canvas the model can genuinely outpaint into: text erased,
    #    subject large and centred, extension margins a mirror-blurred
    #    continuation of the scene (not a flat border it would just reproduce).
    padded = _outpaint_input(im, width, height, extra_erase=[])

    # 2. upload as the edit input
    buf = io.BytesIO()
    padded.save(buf, format="PNG")
    data = buf.getvalue()
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="cover.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        base + "/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        up = json.load(r)
    fname = up["name"]

    # 3. build the Flux 2 Klein EDIT graph through painter's registry. The bare
    #    graphs/edit_flux2.json is a TEMPLATE: its unet/clip/vae loaders are
    #    empty and its prompt node is untouched, so submitting it as-is fails on
    #    the backend (no model, no prompt). Registry.build() fingerprints the
    #    installed models to fill the loaders, pairs the encoder + VAE, injects
    #    the prompt into encode_pos, points load_image at the upload, and
    #    validates the whole thing against the live object_info — the same path
    #    the painter app uses for its "edit" mode.
    reg = R.Registry()
    entry = reg.mode_model("edit")
    if entry is None:
        raise RuntimeError(
            "no Flux 2 edit model available to ComfyUI "
            "(registry root %s) — cannot outpaint" % R.MODEL_ROOT
        )
    try:
        object_info = G.fetch_object_info(base)
    except Exception:  # validate against nothing rather than refuse to run
        object_info = None
    prompt_text = (
        "Remove every piece of text: all lettering, captions, titles, logos and "
        "watermarks, and any Japanese, Chinese or Korean (CJK) characters, "
        "including small or vertically-stacked text in the corners. Keep the main "
        "subject centred and unchanged. Seamlessly outpaint and extend the "
        "photographic background outward to fill the entire wide frame, matching "
        "the lighting, colour and texture of the scene so the extension is "
        "invisible. No borders, no frames, no words, no letters of any kind."
    )
    built = reg.build(
        entry,
        {
            "edit": True,
            "positive": prompt_text,
            "input_image": fname,
            "input_images": [fname],
            "seed": int.from_bytes(os.urandom(6), "big"),
            "filename_prefix": "systheme-edit",
        },
        object_info=object_info,
    )
    tmpl = built["prompt"]
    log(f"comfy edit graph built on {entry.name}")

    # 4. submit and wait
    cid = uuid.uuid4().hex
    payload = json.dumps({"prompt": tmpl, "client_id": cid}).encode()
    req = urllib.request.Request(base + "/prompt", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        pid = json.load(r)["prompt_id"]
    log(f"comfy job {pid} submitted; waiting")
    out_img = None
    for _ in range(600):  # up to ~10 min
        time.sleep(1.0)
        with urllib.request.urlopen(base + f"/history/{pid}", timeout=15) as r:
            hist = json.load(r)
        if pid in hist:
            outs = hist[pid].get("outputs", {})
            for node_out in outs.values():
                for img in node_out.get("images", []):
                    out_img = img
                    break
            if out_img:
                break
    if not out_img:
        raise RuntimeError("comfy produced no image")
    q = urllib.parse.urlencode(
        {"filename": out_img["filename"], "subfolder": out_img.get("subfolder", ""), "type": out_img.get("type", "output")}
    )
    with urllib.request.urlopen(base + "/view?" + q, timeout=30) as r:
        result = Image.open(io.BytesIO(r.read())).convert("RGB")
    if result.size != (width, height):
        result = result.resize((width, height), Image.LANCZOS)
    return result


import urllib.parse  # noqa: E402  (used by render_comfy)


# --------------------------------------------------------------------------- #
#  apply: hand the finished wallpaper to wal-set.sh
# --------------------------------------------------------------------------- #
def apply_theme(path: Path) -> bool:
    wal = SCRIPTS / "wal-set.sh"
    if not wal.exists():
        log(f"wal-set.sh not found at {wal}; wrote wallpaper only")
        return False
    env_wrap = SCRIPTS / "hypr-session-env.sh"
    cmd = ([str(env_wrap)] if env_wrap.exists() else []) + [str(wal), str(path)]
    log("applying theme via wal-set.sh")
    try:
        r = subprocess.run(cmd, timeout=120)
    except Exception as e:
        log(f"wal-set.sh failed to run: {e}")
        return False
    return r.returncode == 0


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "wallpaper"


def parse_rect(s: str) -> tuple[int, int, int, int]:
    parts = [int(p) for p in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("rect must be X0,Y0,X1,Y1")
    return tuple(parts)  # type: ignore[return-value]


def build(
    cover: Path,
    width: int,
    height: int,
    method: str,
    comfy_url: str,
    extra_erase: list[tuple[int, int, int, int]],
) -> tuple["Image.Image", str]:
    im = Image.open(cover).convert("RGB")
    bg = _corner_bg(im)
    uni = _bg_uniformity(im, bg)
    log(f"cover {im.size[0]}x{im.size[1]}, background uniformity {uni:.2f}")

    want_comfy = method == "comfy" or (method == "auto")
    if want_comfy and comfy_healthy(comfy_url):
        try:
            return render_comfy(im, width, height, comfy_url), "comfy"
        except Exception as e:
            if method == "comfy":
                raise
            log(f"comfy route failed ({e}); falling back to flat")
    elif method == "comfy":
        raise RuntimeError(f"ComfyUI backend not healthy at {comfy_url}")
    else:
        log("ComfyUI backend not reachable; using flat route")

    return render_flat(im, width, height, extra_erase), "flat"


def main(argv: list[str] | None = None) -> int:
    global _QUIET
    ap = argparse.ArgumentParser(prog="systheme", description="album cover -> 16:9 wallpaper + wal systheme")
    ap.add_argument("cover", type=Path, help="album cover image path")
    ap.add_argument("--name", default=None, help="output basename")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--method", choices=["auto", "comfy", "flat"], default="auto")
    ap.add_argument("--comfy-url", default=DEFAULT_COMFY)
    ap.add_argument("--erase", action="append", type=parse_rect, default=[])
    ap.add_argument("--no-set", dest="apply", action="store_false")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)
    _QUIET = args.quiet

    if not args.cover.exists():
        sys.stderr.write(f"systheme: no such cover: {args.cover}\n")
        return 2

    name = slugify(args.name or args.cover.stem)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = (args.out_dir / f"{name}-{args.width}x{args.height}.png").resolve()

    try:
        wall, method = build(args.cover, args.width, args.height, args.method, args.comfy_url, args.erase)
    except Exception as e:
        sys.stderr.write(f"systheme: {e}\n")
        return 1
    wall.save(out)
    log(f"wrote {out} ({method})")

    applied = False
    if args.apply:
        applied = apply_theme(out)

    if args.json:
        print(json.dumps({"wallpaper": str(out), "method": method, "applied": applied, "width": args.width, "height": args.height}))
    else:
        print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
