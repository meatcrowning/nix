#!/usr/bin/env bash
# Fedora/book only. Install after applying sys/book-builder.nix on top:
# SUDO_ASKPASS_REASON="enabling top build offload" sudo -A bash tools/book-builder-setup.sh KEY
# KEY is a dedicated private SSH key whose public half is in sys/book-builder.nix.
set -euo pipefail
[[ $(hostname -s) == book && $EUID == 0 ]] || { echo 'run as root on book' >&2; exit 1; }
key=${1:?provide the dedicated builder private key path}
expected='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHjIhMjqF0Kv6UWEj5W5oG0+gZ2NnKBbSFFdWV0IwdeY'
[[ $(ssh-keygen -y -f "$key" | cut -d " " -f 1-2) == "$expected" ]] || { echo 'builder key does not match top configuration' >&2; exit 1; }
install -m 600 -o root -g root "$key" /etc/nix/book-builder-key
hostkey=$(printf '%s' 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHMUAkUeo64TjDSKp2t13ovJnoJceDo3m+J9xlOunPgo' | base64 -w0)
config=$(mktemp /etc/nix/book-builder.conf.XXXXXX)
trap 'rm -f "$config"' EXIT
printf 'builders = ssh://nix-ssh@top x86_64-linux /etc/nix/book-builder-key 1 1 big-parallel - %s\nbuilders-use-substitutes = true\n' "$hostkey" > "$config"
# Query top before realising build dependencies, so previously built outputs
# download directly without filling book with x86 compiler toolchains.
# Trust is scoped to this SSH store and the pinned host key, not all imports.
printf 'extra-substituters = ssh://nix-ssh@top?ssh-key=/etc/nix/book-builder-key&base64-ssh-public-host-key=%s&trusted=true\n' "$hostkey" >> "$config"
chmod 644 "$config"
mv "$config" /etc/nix/book-builder.conf
# Preserve Determinate's generated file and all unrelated custom settings.
touch /etc/nix/nix.custom.conf
if ! grep -qxF 'include /etc/nix/book-builder.conf' /etc/nix/nix.custom.conf; then
  printf '\ninclude /etc/nix/book-builder.conf\n' >> /etc/nix/nix.custom.conf
fi
systemctl restart nix-daemon.service
printf 'book: top enabled for x86 build jobs\n'
