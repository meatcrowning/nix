#!/usr/bin/env python3
"""Fetch the pinned Qwen3.8 vision projector on top; no daemon or GPU is touched."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile
import urllib.request

REV = "a5885499d443cbf4a7998001508ddb3b279eeb5f"
DIGEST = "02262642680a6ea1e44aba92ad3fa551032803f6dc39f880b3cac82a55fea085"
SIZE = 629247168
URL = ("https://huggingface.co/sdkyuan/qwen3.8-27B-qat-q2_0-gguf/resolve/"
       + REV + "/mmproj-qwen38-27b-qat-q8_0.gguf")
DEFAULT = "/home/lam/.local/share/qwen38/" + DIGEST + ".gguf"


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
    fd, name = tempfile.mkstemp(prefix=".qwen38-", dir=target.parent)
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
