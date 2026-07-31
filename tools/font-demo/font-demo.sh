#!/usr/bin/env bash
# font-demo - open the three-way pixel-font specimen window on the real screen.
#
#   ~/nix/tools/font-demo/font-demo.sh
#
# Re-runnable and self-contained. It builds the three candidate faces into
# ~/.cache/font-demo if they are not there, then opens the window. NOTHING is
# installed: the faces are loaded privately with QFontDatabase.addApplicationFont,
# ~/.local/share/fonts is not written, fontconfig is not touched, and
# home/pkgs/desktop/font.nix is not edited. This is a demo, not a change.
#
# Environment reuse: the demo needs PySide6 + the Qt plugin/QML paths, which the
# `goetia` wrapper (home/prog/board.nix) already sets up. Rather than add a
# derivation for a throwaway window, we source the wrapper's exported env and
# exec its python at our own script. If goetia is ever removed, any of the other
# seven app wrappers works the same way - change WRAPPER below.
#
# Rebuild the fonts from scratch with:  rm -rf ~/.cache/font-demo
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE="${FONT_DEMO_DIR:-$HOME/.cache/font-demo}"
WRAPPER="${FONT_DEMO_WRAPPER:-goetia}"

# THIS IS THE ONE THING UNDER tools/ THAT IS SUPPOSED TO OPEN A WINDOW HE CAN
# SEE, and that makes it a loaded gun in a directory otherwise full of harnesses
# an agent runs unattended. It is a specimen for a HUMAN to look at; run from an
# agent it is indistinguishable from the thing he reported on 2026-07-30 ("test
# windows keep popping up"). So: refuse unless a terminal is attached, which an
# agent's shell has not got.
if [ ! -t 0 ] && [ "${FONT_DEMO_ON_HIS_SCREEN:-0}" != 1 ]; then
  cat >&2 <<'MSG'
font-demo: refusing to open a window with no terminal attached.
  This opens a REAL window on the REAL screen - it is a specimen for a person,
  not a test. If you are an agent: you may not run this. See AGENTS.md ->
  "Testing without interfering with the user"; use tools/sandbox.sh or
  QT_QPA_PLATFORM=offscreen instead.
  If you meant it and there is genuinely no tty:  FONT_DEMO_ON_HIS_SCREEN=1
MSG
  exit 91
fi

# --- 1. the three candidate faces ------------------------------------------
if [ ! -f "$CACHE/current.ttf" ] || [ ! -f "$CACHE/merged.ttf" ] \
   || [ ! -f "$CACHE/merged-noellipsis.ttf" ]; then
  echo "font-demo: building candidate faces into $CACHE ..."
  PACK="$(nix build --no-link --print-out-paths nixpkgs#ultimate-oldschool-pc-font-pack)"
  DONOR="$PACK/share/fonts/truetype/PxPlus_IBM_VGA_9x16.ttf"
  [ -f "$DONOR" ] || { echo "font-demo: donor font not found at $DONOR" >&2; exit 1; }
  FONT_DEMO_DIR="$CACHE" nix shell --impure \
    --expr 'with import <nixpkgs> {}; python3.withPackages(ps:[ps.fonttools])' \
    -c python3 "$HERE/build-fonts.py" "$DONOR"
fi

# --- 2. the window ----------------------------------------------------------
WRAP_PATH="$(readlink -f "$(command -v "$WRAPPER")")"
[ -n "$WRAP_PATH" ] || { echo "font-demo: no '$WRAPPER' on PATH to borrow a Qt env from" >&2; exit 1; }

# Everything in the wrapper except its shebang and its final exec is env setup.
eval "$(grep -v -e '^#!' -e '^exec ' "$WRAP_PATH")"
PY="$(sed -n 's/^exec "\([^"]*\)".*/\1/p' "$WRAP_PATH")"
[ -x "$PY" ] || { echo "font-demo: could not find the python inside $WRAP_PATH" >&2; exit 1; }

FONT_DEMO_DIR="$CACHE" exec "$PY" "$HERE/main.py" "$@"
