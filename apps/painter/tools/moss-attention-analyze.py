#!/usr/bin/env python3
"""Compare the two cube/sphere experiment scenes; select on left, report right.

Run with Comfy's Python and --baseline OLD_OUTPUT --trial NEW_OUTPUT --out DIR.
Colour masks are an approximate reference for these two controlled scenes only.
All maps use the same 5th/99th percentile display scale and 0.5 mask threshold.
"""
import argparse
import json
from pathlib import Path

# Import torch first so its bundled runtime libraries are available on NixOS.
import torch
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def load(root, label):
    report = json.loads((root / (label + '.json')).read_text())
    with np.load(root / (label + '.npz')) as data:
        maps = dict(data)
    image = Image.open(next(root.glob(label + '_*.png'))).convert('RGB').resize((384, 384))
    rgb = np.asarray(image).astype(float)
    r, g, b = rgb.transpose(2, 0, 1)
    masks = [(r > g * 1.4) & (r > b * 1.4) & (r > 64),
             (b > r * 1.4) & (b > g * 1.15) & (b > 64)]
    return report, maps, image, masks


def noun_contrast(dot, cosine):
    """Exploratory rival suppression for exactly two distinct nouns, not attributes."""
    assert len(dot) == len(cosine) == 2
    result = np.maximum(cosine - cosine[::-1], 0)
    for i in range(2):
        lo, hi = np.percentile(dot[i], [5, 99])
        strength = np.clip((dot[i] - lo) / max(float(hi - lo), 1e-12), 0, 1)
        result[i] *= strength ** 2
    return result


def candidates(report, maps):
    result = dict(maps)
    for prefix in ('', 'dot_', 'cosine_'):
        keys = [k for k in maps if k.startswith(prefix + 'layer')]
        if not keys:
            continue
        result[prefix + 'all'] = sum(maps[k] * report['counts'][k] for k in keys) / sum(report['counts'][k] for k in keys)
        for layer in {k.split('_band')[0] for k in keys}:
            subset = [k for k in keys if k.startswith(layer + '_band')]
            result[layer + '_all'] = sum(maps[k] * report['counts'][k] for k in subset) / sum(report['counts'][k] for k in subset)
    for key in maps:
        if key.startswith('dot_'):
            suffix = key.removeprefix('dot_')
            result['gated_' + suffix] = noun_contrast(maps[key], maps['cosine_' + suffix])
    return result


def display(raw, blur):
    lo, hi = np.percentile(raw, [5, 99])
    normalized = np.clip((raw - lo) / max(float(hi - lo), 1e-12), 0, 1)
    image = Image.fromarray((normalized * 255).astype('uint8'))
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(image.resize((384, 384), Image.Resampling.BILINEAR)) / 255


def measure(maps, masks, blur):
    values = []
    for raw, mask in zip(maps, masks):
        selected = display(raw, blur) > .5
        intersection = (selected & mask).sum()
        values.append({'iou': float(intersection / max(1, (selected | mask).sum())),
                       'coverage': float(intersection / max(1, mask.sum())),
                       'precision': float(intersection / max(1, selected.sum()))})
    return {k: sum(v[k] for v in values) / len(values) for k in values[0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'trial', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument("--output-map", default="", help="Explicit output-feature candidate; otherwise select on left scene")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    groups = {'original': (args.baseline, 'capture'),
              'sparse': (args.trial, 'sparse'), 'output': (args.trial, 'output')}
    chosen, summary, loaded = {}, {}, {}
    for group, (root, suffix) in groups.items():
        scenes = [load(root, side + '_' + suffix) for side in ('left', 'right')]
        loaded[group] = scenes
        options = candidates(*scenes[0][:2])
        if group == 'original':
            key, blur = 'all', 0
        else:
            key, blur = max(((key, blur) for key in options for blur in (0, 1, 2)),
                            key=lambda choice: measure(options[choice[0]], scenes[0][3], choice[1])['iou'])
        if group == 'output' and args.output_map:
            key, blur = args.output_map, 1
        chosen[group] = (key, blur)
        summary[group] = {'map': key, 'blur_latent_pixels': blur}
        for side, scene in zip(('left', 'right'), scenes):
            options = candidates(*scene[:2])
            summary[group][side] = measure(options[key], scene[3], blur)
        if group != 'original':
            summary[group]['seconds'] = scenes[0][0]['sampler_seconds']
            summary[group]['capture_cuda_seconds'] = scenes[0][0]['capture_cuda_seconds']
    canvas = Image.new('RGB', (384 * 4, 420 * 4), 'white')
    draw = ImageDraw.Draw(canvas)
    for si, side in enumerate(('left', 'right')):
        for wi, word in enumerate(('cube', 'sphere')):
            row = si * 2 + wi
            base = loaded['original'][si][2]
            canvas.paste(base, (0, row * 420 + 36))
            draw.text((8, row * 420 + 10), side + ': ' + word, fill='black')
            for col, group in enumerate(groups, 1):
                scene = loaded[group][si]
                key, blur = chosen[group]
                heat = display(candidates(*scene[:2])[key][wi], blur)
                # Fade weak scores out; .5 remains the midpoint used for metrics.
                strength = np.clip((heat - .35) / .3, 0, 1)
                alpha = .8 * (strength * strength * (3 - 2 * strength))[..., None]
                pixels = np.asarray(scene[2]).astype(float)
                overlay = pixels * (1 - alpha) + np.array([255, 220, 0]) * alpha
                canvas.paste(Image.fromarray(overlay.astype('uint8')), (col * 384, row * 420 + 36))
                draw.text((col * 384 + 8, row * 420 + 10), group + ': ' + key + ', blur ' + str(blur), fill='black')
    canvas.save(args.out / 'comparison.png')
    baseline = json.loads((args.trial / 'left_baseline.json').read_text())
    summary['baseline_seconds'] = baseline['sampler_seconds']
    summary['left_latents_identical'] = all(loaded[g][0][0]['latent_sha256'] == baseline['latent_sha256'] for g in groups)
    summary['right_latents_identical'] = len({loaded[g][1][0]['latent_sha256'] for g in groups}) == 1
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
