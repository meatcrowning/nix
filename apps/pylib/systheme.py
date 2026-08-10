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

  * ``comfy``  — the general, picture-faithful route: the headless ComfyUI
    backend (apps/painter's Flux 2 Klein *edit* graph) removes text and
    outpaints a photographic background seamlessly. Used when the backend is
    reachable AND healthy. LOCAL models only (loopback / ssh-tunnelled 8188).
  * ``flat``   — a dependency-light route for covers on a UNIFORM background
    (the Monody green, the Love Deluxe cream): text on the flat field is
    erased by filling the sampled background colour, the subject is recentred,
    and the flat field is extended to 16:9. For a flat-background cover this is
    visually equivalent to the generative pass; for a busy background it is the
    graceful fallback, and the tool says which it used.

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
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
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


def _text_bands(mask: "Image.Image", margin_frac: float = 0.45) -> list[tuple[int, int, int, int]]:
    """Best-effort: isolated thin fg bands sitting in a background margin = text.

    Scans the left and top margins for contiguous fg row/column runs that are
    thin relative to the frame and separated from the main subject by clear
    background. Returns bboxes to blank. Heuristic — the comfy route is the
    robust one; this keeps the flat route honest for label strips like Monody's
    top text and Love Deluxe's left "sade love deluxe".
    """
    w, h = mask.size
    out: list[tuple[int, int, int, int]] = []
    m = mask.load()

    # rows with fg only inside the LEFT margin (a left-aligned label column)
    lw = int(w * margin_frac)
    runs = []
    start = None
    for y in range(h):
        c = sum(1 for x in range(lw) if m[x, y])
        on = c > 3
        if on and start is None:
            start = y
        elif not on and start is not None:
            runs.append((start, y - 1))
            start = None
    if start is not None:
        runs.append((start, h - 1))
    gap_min = max(24, int(w * 0.03))
    for y0, y1 in runs:
        band_h = y1 - y0 + 1
        if band_h > h * 0.16:  # too tall to be a label -> it's the subject/arm
            continue
        # column fg strength across the band (>=2 px = "on", so single-pixel
        # jpeg noise does not bridge the gap between a label and the subject).
        col = [sum(1 for yy in range(y0, y1 + 1) if m[x, yy]) for x in range(w)]
        on = [c >= 2 for c in col]
        try:
            x_start = next(x for x in range(w) if on[x])
        except StopIteration:
            continue
        # the label ends at the FIRST clear background gap; if none opens before
        # mid-frame the band is fused with the subject, so leave it alone.
        x_right = None
        run_empty = 0
        for x in range(x_start, w):
            if on[x]:
                run_empty = 0
            else:
                run_empty += 1
                if run_empty >= gap_min:
                    x_right = x - run_empty
                    break
        if x_right is None or x_right <= x_start:
            continue
        if (x_right - x_start) > w * 0.5 or x_start > w * 0.5:
            continue  # too wide / too far right to be a margin label
        sub = mask.crop((x_start, y0, x_right + 1, y1 + 1))
        bb = sub.getbbox()
        if bb:
            out.append((x_start + bb[0], y0 + bb[1], x_start + bb[2], y0 + bb[3]))

    # rows with fg only inside the TOP margin (a top label strip, e.g. Monody)
    th = int(h * margin_frac)
    runs = []
    start = None
    for y in range(th):
        c = sum(1 for x in range(w) if m[x, y])
        on = 3 < c < w * 0.85
        if on and start is None:
            start = y
        elif not on and start is not None:
            runs.append((start, y - 1))
            start = None
    # a top strip only counts if clear background separates it from below
    for y0, y1 in runs:
        if (y1 - y0 + 1) > h * 0.22:
            continue
        below = mask.crop((0, y1 + 1, w, min(h, y1 + 1 + int(h * 0.04))))
        if below.getbbox() is None:  # gap of clean bg under it
            sub = mask.crop((0, y0, w, y1 + 1))
            bb = sub.getbbox()
            if bb:
                out.append((bb[0], y0 + bb[1], bb[2], y0 + bb[3]))
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
    rects = _text_bands(mask) + list(extra_erase)
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
    import importlib.util
    import time
    import uuid

    painter = Path(__file__).resolve().parent.parent / "painter"
    spec = importlib.util.spec_from_file_location("painter_graph", painter / "graph.py")
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("cannot locate painter/graph.py")
    # graph.py imports registry/pngmeta relative to painter/ — run from there
    sys.path.insert(0, str(painter))
    try:
        import registry  # type: ignore  # noqa: F401
    finally:
        pass

    base = base.rstrip("/")

    # 1. pad the cover onto a 16:9 canvas of its own background so the model has
    #    a frame to outpaint into, with the subject already centred.
    padded = render_flat(im, width, height, extra_erase=[])

    # 2. upload as the edit input
    import io

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

    # 3. build the edit graph and point it at the uploaded frame
    tmpl = json.load(open(painter / "graphs" / "edit_flux2.json"))
    prompt_text = (
        "Remove all text, lettering, logos and captions. Keep the central "
        "figure exactly, centred, and seamlessly extend the background to fill "
        "the whole frame. Photographic, no borders, no words."
    )
    for node in tmpl.values():
        if not isinstance(node, dict):
            continue
        meta = node.get("_meta", {})
        role = meta.get("painter_role")
        ins = node.get("inputs", {})
        if role == "image" or node.get("class_type") == "LoadImage":
            ins["image"] = fname
        if role in ("positive", "prompt") and "text" in ins:
            ins["text"] = prompt_text
        if node.get("class_type") == "RandomNoise" and "noise_seed" in ins:
            ins["noise_seed"] = int.from_bytes(os.urandom(4), "big")

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
