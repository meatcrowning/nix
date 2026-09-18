#!/usr/bin/env python3
"""Fetch the pinned Bonsai weights on top; no daemon or GPU is touched."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile
import urllib.request

REV = "6ed5e12bf84b7a63069882c91dd9e9218647d17b"
DIGEST = "3907dc1658db1f78a9826bf8d5bcb8dc65db0d466388937af57f2294fae62ec1"
SIZE = 7206168928
URL = ("https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf/resolve/"
       + REV + "/Ternary-Bonsai-2-27B-PQ2_0.gguf")
DEFAULT = "/home/lam/.local/share/bonsai/" + DIGEST + ".gguf"


def verified(path):
    if path.stat().st_size != SIZE:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == DIGEST


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=DEFAULT)
    args = parser.parse_args()
    target = Path(args.path)
    if target.exists():
        if not verified(target):
            raise SystemExit("Existing file does not match the pinned model; left untouched")
        print("Verified existing model:", target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".bonsai-", dir=target.parent)
    part = Path(name)
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(URL, timeout=120) as response:
            total = 0
            while chunk := response.read(8 * 1024 * 1024):
                out.write(chunk)
                total += len(chunk)
                if total > SIZE:
                    raise RuntimeError("Download exceeds pinned size")
                if total // (512 * 1024 * 1024) != (total - len(chunk)) // (512 * 1024 * 1024):
                    print(f"Downloaded {total / 1e9:.1f}/{SIZE / 1e9:.2f} GB", flush=True)
            out.flush()
            os.fsync(out.fileno())
        if not verified(part):
            raise RuntimeError("Downloaded model failed size/SHA-256 verification")
        part.chmod(0o644)  # ollama's DynamicUser needs read access.
        # Atomic no-clobber publication, including when two fetchers race.
        os.link(part, target)
        print("Verified and installed:", target)
    finally:
        part.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
