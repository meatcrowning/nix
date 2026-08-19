#!/bin/sh
# font-private-install.sh — fetch proprietary fonts from the PRIVATE nix-fonts
# repo into ~/.local/share/fonts.
#
# Tahoma cannot live in the public ~/nix checkout, so it is pulled here from a
# private remote using the gh credential helper (`!gh auth git-credential`) —
# the same authentication the claude-state and nix-docs syncs rely on. The repo
# is single-writer (only this mechanism ever changes it), so this is a pure
# read: clone once, fast-forward to origin/main each run, copy the font out.
# A failed fetch (offline, or first run before the repo existed) leaves whatever
# is already installed untouched and exits 0 — a font already present must never
# be torn down by a network blip.
#
# Deployed to ~/.config/scripts by home/srvs/font-private.nix; driven by the
# font-private-sync systemd user unit + timer and called from the home.activation
# hook so the current switch installs it immediately on both machines.

set -eu
REMOTE="${FONT_REMOTE:-https://github.com/meatcrowning/nix-fonts.git}"
CHECKOUT="${FONT_CHECKOUT:-$HOME/.local/share/nix-fonts}"
FONTS_DIR="${FONTS_DIR:-$HOME/.local/share/fonts}"

mkdir -p "$FONTS_DIR"

if [ ! -d "$CHECKOUT/.git" ]; then
  # First run (or the checkout was wiped). Depth 1 — we only ever read HEAD.
  if git clone -q --depth 1 "$REMOTE" "$CHECKOUT" 2>/dev/null; then
    :   # cloned
  else
    echo "font-private: clone failed ($REMOTE) — keeping installed font"
    exit 0
  fi
else
  # Refresh. Fetch then fast-forward the mirror to origin/main; ignore a fetch
  # failure (offline) and keep the last good copy.
  if git -C "$CHECKOUT" fetch -q --depth 1 origin main 2>/dev/null; then
    git -C "$CHECKOUT" reset -q --hard FETCH_HEAD
  fi
fi

if [ -f "$CHECKOUT/tahoma.ttf" ]; then
  cp -f "$CHECKOUT/tahoma.ttf" "$FONTS_DIR/tahoma.ttf"
  fc-cache -f "$FONTS_DIR" >/dev/null 2>&1 || true
  echo "font-private: installed tahoma.ttf into $FONTS_DIR"
else
  echo "font-private: no tahoma.ttf in checkout"
fi
