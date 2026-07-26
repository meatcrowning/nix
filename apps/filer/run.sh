#!/usr/bin/env bash
# Dev launcher: run filer against the flake devShell (python3 + pyside6 +
# qtdeclarative) without installing anything. For the packaged binary use
# `nix run .` (see flake.nix).
here="$(cd "$(dirname "$0")" && pwd)"
exec nix develop "path:$here" --command python3 "$here/main.py" "$@"
