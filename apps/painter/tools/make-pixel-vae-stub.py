#!/usr/bin/env python3
"""Create the stub VAE that pixel-space models need.

Models like `zeta-chroma-base-x0-pixel-dino-distance` predict pixels directly, so
there is nothing to decode -- but ComfyUI's graph still requires a VAE object on
`VAEDecode`.  comfy/sd.py matches on the presence of a key literally named
`pixel_space_vae` and swaps in PixelspaceConversionVAE (identity, 3 channels,
downscale 1).  Nothing reads the tensor's contents, so a single scalar is enough.
"""

from __future__ import annotations

import argparse
import json
import os
import struct

DEFAULT_OUT = "/home/lam/models/vae/pixel_space_vae_stub.safetensors"


def build() -> bytes:
    payload = struct.pack("<f", 1.0)
    header = {
        "pixel_space_vae": {"dtype": "F32", "shape": [1], "data_offsets": [0, len(payload)]},
        "__metadata__": {
            "painter": "pixel-space passthrough VAE stub",
            "why": "satisfies VAEDecode for pixel-space models; contents are unused",
        },
    }
    blob = json.dumps(header, separators=(",", ":")).encode("utf-8")
    # safetensors requires the header to be 8-byte aligned.
    pad = (-len(blob)) % 8
    blob += b" " * pad
    return struct.pack("<Q", len(blob)) + blob + payload


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    if os.path.exists(args.out) and not args.force:
        print(f"already exists: {args.out}")
        return 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    data = build()
    with open(args.out, "wb") as fh:
        fh.write(data)
    print(f"wrote {args.out} ({len(data)} bytes)")

    # Prove it reads back the way ComfyUI will see it.
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import fingerprint as fp

    h = fp.read_header(args.out)
    assert "pixel_space_vae" in h.keys, "stub is missing its marker key"
    fam, dims = fp.detect_vae(h)
    print(f"verified: family={fam} dims={dims}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
