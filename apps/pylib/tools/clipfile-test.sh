#!/usr/bin/env bash
# clipfile-test.sh — does pylib/clipfile.py own the clipboard, and does it offer
# a file as a FILE?
#
# It cannot be tested against the live session: setting the selection there
# would take his clipboard (AGENTS.md -> "Testing without interfering with the
# user"), and reading it back would say nothing about our own offer anyway. So
# the whole copy/paste happens inside a HEADLESS SWAY — no output, no window,
# nothing on screen, and its own seat and clipboard.
#
# It cannot fall through onto his session, positively rather than by promise:
# the compositor is started with `XDG_RUNTIME_DIR` pointed at a scratch dir, so
# the only Wayland socket any client here can reach is the one we made. His is
# not in that directory. WLR_BACKENDS=headless is what keeps wlroots from
# opening a window in his session instead.
#
# sway rather than a nested Hyprland for exactly that reason: a nested Hyprland
# is a WINDOW in the live session (that is what tools/sandbox.sh exists to hide)
# and it takes the seat for a moment at map time. This one is never on screen at
# all. It comes from `nix shell nixpkgs#sway` if it is not already on PATH.
#
# Usage: apps/pylib/tools/clipfile-test.sh

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CLIPFILE="$HERE/../clipfile.py"

RUN="$(mktemp -d /tmp/clipt-XXXXXX)"
LOG="$RUN/sway.log"
FAILED=0
ok()  { printf '   \033[32mok\033[0m   %s\n' "$*"; }
bad() { printf '   \033[31mFAIL\033[0m %s\n' "$*"; FAILED=1; }

cleanup() {
  [ -n "${CLEANED:-}" ] && return 0
  CLEANED=1
  [ -n "${SWAYPID:-}" ] && kill "$SWAYPID" 2>/dev/null
  sleep 0.2
  [ -n "${SWAYPID:-}" ] && kill -9 "$SWAYPID" 2>/dev/null
  rm -rf "$RUN"
}
trap cleanup EXIT INT TERM

if command -v sway >/dev/null 2>&1; then
  SWAY=(sway)
else
  command -v nix >/dev/null 2>&1 || { echo "need sway, or nix to fetch it"; exit 1; }
  SWAY=(nix shell nixpkgs#sway --command sway)
fi

printf '\n\033[1m== a compositor he cannot see\033[0m\n'
printf 'exec true\n' > "$RUN/config"
# XDG_RUNTIME_DIR is the isolation: his socket is not in here, so nothing below
# can reach it even if sway never starts. WAYLAND_DISPLAY/HYPRLAND_* are cleared
# so wlroots cannot decide to nest itself into his session.
env -u WAYLAND_DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE -u DISPLAY \
    XDG_RUNTIME_DIR="$RUN" WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 \
    "${SWAY[@]}" -c "$RUN/config" > "$LOG" 2>&1 &
SWAYPID=$!

WL=""
for _ in $(seq 1 100); do
  sleep 0.2
  for s in "$RUN"/wayland-*; do
    case "$s" in *.lock) continue ;; esac
    [ -S "$s" ] && WL="$(basename "$s")"
  done
  [ -n "$WL" ] && break
  kill -0 "$SWAYPID" 2>/dev/null || break
done
[ -n "$WL" ] || { bad "headless sway never came up"; sed -n 1,20p "$LOG"; exit 1; }
ok "headless sway on $RUN/$WL (his session is untouched: different XDG_RUNTIME_DIR)"

# Every client below runs against THAT socket and nothing else.
n() { env XDG_RUNTIME_DIR="$RUN" WAYLAND_DISPLAY="$WL" "$@"; }

printf '\n\033[1m== a file on the clipboard\033[0m\n'
CLIP="$RUN/some clip #1.mp4"
printf 'x' > "$CLIP"
if n python3 "$CLIPFILE" "$CLIP" 2>"$RUN/err"; then
  ok "clipfile exits 0 once the selection is set"
else
  bad "clipfile failed: $(cat "$RUN/err")"
fi

types="$(n wl-paste --list-types 2>/dev/null)"
for want in text/uri-list x-special/gnome-copied-files text/plain; do
  case "$types" in
    *"$want"*) ok "offers $want" ;;
    *) bad "does NOT offer $want (offered: $(echo "$types" | tr '\n' ' '))" ;;
  esac
done

uri="$(n wl-paste --no-newline --type text/uri-list 2>/dev/null | od -c | tr '\n' ' ')"
case "$uri" in
  *'f   i   l   e   :'*) ok "the uri-list is a file:// URI" ;;
  *) bad "unexpected uri-list payload: $uri" ;;
esac
if n wl-paste --no-newline --type text/uri-list 2>/dev/null \
   | python3 -c 'import sys; sys.exit(0 if sys.stdin.buffer.read().endswith(b"\r\n") else 1)'; then
  ok "...CRLF-terminated, per RFC 2483"
else
  bad "the uri-list is not CRLF-terminated: $uri"
fi
case "$uri" in
  *'%   2   3'*) ok "...and '#' in the name is percent-encoded" ;;
  *) bad "'#' was not percent-encoded: $uri" ;;
esac

gnome="$(n wl-paste --no-newline --type x-special/gnome-copied-files 2>/dev/null)"
case "$gnome" in
  copy$'\n'file://*) ok "the gnome-copied-files payload is a copy, not a cut" ;;
  *) bad "unexpected gnome-copied-files payload: $gnome" ;;
esac

printf '\n\033[1m== the holder outlives the caller\033[0m\n'
# The process that copied exited before any paste above ran, so every one of
# them was served by the forked holder. Prove it lets go, too.
if n wl-paste --no-newline --type text/uri-list >/dev/null 2>&1; then
  ok "still pasteable after the process that copied it exited"
else
  bad "the selection died with the caller"
fi
n wl-copy "something else" >/dev/null 2>&1
sleep 0.5
if pgrep -f "clipfile.py $RUN" >/dev/null 2>&1; then
  bad "the holder is still running after the clipboard moved on"
else
  ok "the holder exits when something else takes the clipboard"
fi

printf '\n'
[ "$FAILED" = 0 ] && { printf '\033[32mall good\033[0m\n'; exit 0; }
printf '\033[31msomething failed\033[0m\n'; exit 1
