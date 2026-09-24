#!/usr/bin/env bash
# Run on top. Evaluate/build there, then copy the closure and activate on pad.
# Usage: tools/deploy-pad.sh build | tools/deploy-pad.sh boot|switch root@PAD
set -euo pipefail
action=${1:-build}
case "$action" in build|boot|switch) ;; *) echo 'usage: deploy-pad.sh build|boot|switch [root@PAD]' >&2; exit 2;; esac
[[ $(cat /proc/sys/kernel/hostname) == top ]] || { echo 'run this on top; pad should not evaluate its own system' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo"
if [[ -n $(git status --porcelain) ]]; then
  echo 'commit or finish repository changes first; deployment builds committed HEAD' >&2
  exit 1
fi
if [[ $action != build ]]; then
  target=${2:?provide root@PAD (hostname or IP)}
  [[ $target =~ ^root@[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || { echo 'target must be root@hostname or root@IPv4' >&2; exit 2; }
  # Refuse an accidental deployment to another host before doing any work.
  [[ $(ssh -o BatchMode=yes "$target" cat /proc/sys/kernel/hostname) == pad ]] || { echo 'target is not pad' >&2; exit 1; }
fi
rev=$(git rev-parse HEAD)
out="$repo/result-pad"
nix build --no-write-lock-file --out-link "$out" "git+file://$repo?rev=$rev#nixosConfigurations.pad.config.system.build.toplevel"
system=$(readlink -f "$out")
printf 'pad system: %s\n' "$system"
[[ $action != build ]] || exit 0
nix-copy-closure --to "$target" "$system"
# A key-only root connection is required: the existing restricted nix-ssh
# builder account cannot activate a system. Keep the key out of the repo.
ssh -o BatchMode=yes "$target" "nix-env --profile /nix/var/nix/profiles/system --set '$system' && '$system/bin/switch-to-configuration' '$action'"
printf 'pad: %s complete (%s)\n' "$action" "$rev"
