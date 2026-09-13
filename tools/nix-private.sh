#!/bin/sh
# Evaluate/build the public flake with non-secret personal configuration.
# Keep the override out of the public lock file. Never use for flake update.
set -eu
case "${1:-}" in
  eval|build|develop|shell) ;;
  *) echo "usage: tools/nix-private.sh eval|build|develop|shell [nix arguments]" >&2; exit 2 ;;
esac
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
private=${NIX_PRIVATE_CONFIG:-$repo/docs/private-config}
if [ ! -f "$private/default.nix" ]; then
  echo "private configuration missing: $private/default.nix; restore the private docs checkout before building" >&2
  exit 1
fi
exec nix "$@" --override-input private-config "path:$private" --no-write-lock-file
