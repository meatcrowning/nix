#!/usr/bin/env python3
"""Install pinned Qwen 2.1 weights and the native Comfy backport on top.

Does not start/restart the backend or run inference. Downloads are resumable;
only checksum-verified files become visible to Painter's model scan.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comfy", type=Path)
    parser.add_argument("--models", type=Path, default=Path("/home/lam/models"))
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    patch = here / "qwen21-backend.patch"
    def git(*argv, **kwargs):
        return subprocess.run(["git", "-C", str(args.comfy), *argv], **kwargs)

    installed = git("apply", "--reverse", "--check", str(patch),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not installed:
        # Fail atomically if upstream or another local patch changed the context.
        git("apply", "--check", str(patch), check=True)
        git("apply", str(patch), check=True)
    print("Qwen 2.1 native backend support installed.", flush=True)
    manifest = json.loads((here / "qwen21-models.json").read_text())
    for item in manifest["files"]:
        dest = args.models / item["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        candidate = dest if dest.exists() else dest.with_suffix(dest.suffix + ".part")
        if candidate != dest:
            url = (f"https://huggingface.co/{manifest['repo']}/resolve/"
                   f"{manifest['revision']}/{item['path']}")
            print(f"Downloading {item['path']} ({item['size'] / 1e9:.2f} GB)", flush=True)
            subprocess.run(["curl", "--fail", "--location", "--retry", "5",
                            "--continue-at", "-", "--output", str(candidate),
                            "--silent", "--show-error", url], check=True)
        print(f"Verifying {candidate.name}", flush=True)
        with candidate.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if candidate.stat().st_size != item["size"] or digest != item["sha256"]:
            raise SystemExit(f"Checksum/size mismatch: {candidate}; not installed")
        if candidate != dest:
            candidate.rename(dest)
        print(f"Ready: {dest.name}", flush=True)
    print("Ready for the next backend start; no generation was run.")


if __name__ == "__main__":
    main()
