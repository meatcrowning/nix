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
# It also sizes the greeter's text: ly is a TUI on the framebuffer console, so
# its scale IS the console font, and the drop-in loads a 14x28 Terminus on
# tty2 before ly starts (why that size, and where the font comes from:
# home/prog/ly.nix). The setfont is prefixed `-` so a missing or unreadable
# font costs a small greeter, never a machine you cannot log in to.
#
# Idempotent — safe to re-run after a reinstall, and the way to refresh the
# system font copy after a terminus bump. Takes effect at the next login,
# never mid-session.
set -eu
[ "$(hostname)" = book ] || {
  echo "this is for book (ly); nothing to do here" >&2
  exit 0
}

UNIT_DIR=/etc/systemd/system/ly@tty2.service.d
DROPIN="$UNIT_DIR/10-supervised.conf"
# home-manager's copy (home/prog/ly.nix) -> where a confined greeter can read
# it. /usr/lib/kbd/consolefonts is lib_t and is setfont's own search path, so
# the unit names the font, not a path.
FONT_SRC=/home/lam/.config/ly/console-font.psf.gz
FONT_DST=/usr/lib/kbd/consolefonts/ly-hidpi.psf.gz

if [ -f "$FONT_SRC" ]; then
  install -m 0644 "$FONT_SRC" "$FONT_DST"
  command -v restorecon >/dev/null 2>&1 && restorecon "$FONT_DST"
  echo "installed $FONT_DST"
else
  echo "WARNING: $FONT_SRC missing — run home-manager switch first; the greeter keeps the default 8x16 font" >&2
fi

install -d -m 0755 "$UNIT_DIR"
cat > "$DROPIN" <<'EOF'
# ly -> the supervised session config, installed by tools/install-ly-supervision.sh
# (content: home/prog/ly.nix). The repo is the source of truth; this drop-in
# is the one root seam.
[Service]
ExecStartPre=-/usr/bin/setfont -C /dev/tty2 ly-hidpi
ExecStart=
ExecStart=/usr/bin/ly --config /home/lam/.config/ly
EOF
systemctl daemon-reload

echo "installed $DROPIN — the supervised session starts at the next login"
