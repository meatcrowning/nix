#!/bin/sh
# One-time root step for the supervised Hyprland session on book
# (home/prog/ly.nix): ly reads /etc/ly/config.ini by default, and that file
# cannot point at a per-user session dir from home-manager. This installs a
# systemd drop-in that starts ly with `--config /home/lam/.config/ly` instead.
# A drop-in is additive and survives dnf updates — unlike an edit of the
# rpm-owned /etc/ly/config.ini or a rewrite of
# /usr/share/wayland-sessions/hyprland.desktop, both of which an update would
# clobber. It is the only root touch the whole mechanism needs; every file ly
# then reads lives in the repo.
#
# Idempotent — safe to re-run after a reinstall. Takes effect at the next
# login, never mid-session.
set -eu
[ "$(hostname)" = book ] || {
  echo "this is for book (ly); nothing to do here" >&2
  exit 0
}

UNIT_DIR=/etc/systemd/system/ly@tty2.service.d
DROPIN="$UNIT_DIR/10-supervised.conf"

install -d -m 0755 "$UNIT_DIR"
cat > "$DROPIN" <<'EOF'
# ly -> the supervised session config, installed by tools/install-ly-supervision.sh
# (content: home/prog/ly.nix). The repo is the source of truth; this drop-in
# is the one root seam.
[Service]
ExecStart=
ExecStart=/usr/bin/ly --config /home/lam/.config/ly
EOF
systemctl daemon-reload

echo "installed $DROPIN — the supervised session starts at the next login"
