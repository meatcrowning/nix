#!/usr/bin/env bash
# player's launcher on `air` — the MacBook, which plays top's library over SMB.
#
# top holds the music (208 GB); air has ~12 GB free, so the audio is never
# copied, only streamed from the mount. What DOES have to travel is the
# metadata: the database (ratings, play counts, cached lyrics) and the art
# cache. This script moves those either side of the app:
#
#     probe top -> touch the automount -> pull the db -> pull thumbs
#     -> run the player -> push the db back
#
# Every one of those steps is allowed to fail. If top is asleep or air is off
# the LAN, the player still starts against the local database: the scanner
# bails without pruning when the root is not a directory, so tracks simply show
# unavailable and nothing is lost. Being off-network must never cost you your
# library. See docs/air-library-share.md.
#
# Only ever invoked on air (home/prog/player.nix picks it for host == "air").
set -uo pipefail

# Names for top, tried in order: the mDNS name answers only on the home LAN;
# `top` is the tailscale MagicDNS name and works from any network the tailnet
# reaches (sys/net/tailscale.nix). PLAYER_SYNC_HOST pins the list to one name.
if [ -n "${PLAYER_SYNC_HOST:-}" ]; then
    CANDIDATES=("$PLAYER_SYNC_HOST")
else
    CANDIDATES=(top.local top)
fi
MOUNT="/run/media/lam/SSD/aud"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN="$HERE/../main.py"
DBSYNC="$HERE/dbsync.py"
ART_LOCAL="${XDG_CACHE_HOME:-$HOME/.cache}/player/art"
PREFS="${XDG_STATE_HOME:-$HOME/.local/state}/player/prefs.json"
PY="${PLAYER_PYTHON:-/usr/bin/python3}"

say() { printf 'player: %s\n' "$*" >&2; }

# ---- dependency preflight -------------------------------------------------
# air runs Fedora's system python, so the deps are dnf/pip's problem, not nix's.
# Name what is missing instead of dying on an import traceback.
#
# Fedora 44 has NO python3-mpv package — the binding is pip-only, and it is a
# pure-ctypes wrapper, so it also needs the library itself (dnf mpv-libs) or it
# fails at import, not at play. mpris_server is likewise pip-only.
check_deps() {
    local missing=() mod pkg
    for pair in "PySide6:dnf install python3-pyside6" \
                "mpv:dnf install mpv-libs && pip install --user python-mpv" \
                "mutagen:dnf install python3-mutagen" \
                "mpris_server:pip install --user mpris-server"; do
        mod="${pair%%:*}"; pkg="${pair#*:}"
        "$PY" -c "import $mod" 2>/dev/null || missing+=("$mod  ($pkg)")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        say "missing python modules:"
        printf '  %s\n' "${missing[@]}" >&2
        return 1
    fi
    say "all python deps present ($PY)"
    return 0
}

if [ "${1:-}" = "--check-deps" ]; then
    check_deps
    exit $?
fi

# ---- is top up? -----------------------------------------------------------
# bash's /dev/tcp, so this needs no nc. A short timeout because the whole point
# is to not sit here when the answer is "no".
#
# But resolve the name OURSELVES first, and with Fedora's python. `top.local`
# is mDNS, which glibc answers by dlopen()ing /usr/lib64/libnss_mdns4_minimal;
# a NIX-built binary links nix's glibc, which looks for that module under its
# own store path, does not find it, and fails every .local lookup with
# "Temporary failure in name resolution". This script runs under whichever bash
# is first on PATH and on air that is ~/.nix-profile/bin/bash — so /dev/tcp
# could never resolve top.local, top_up() was false forever, and the player
# launched "offline" on a LAN where top was sitting right there. Fedora's
# /usr/bin/python3 uses Fedora's glibc and resolves it fine.
#
# Only the probe needs the address: ssh is Fedora's (/usr/sbin/ssh) and
# resolves the name itself, and keeping the NAME there keeps known_hosts and
# the authorized key matching what Part B set up.
resolve() { "$PY" -c 'import socket,sys
try: print(socket.gethostbyname(sys.argv[1]))
except OSError: print(sys.argv[1])' "$1" 2>/dev/null; }

top_up() { timeout 2 bash -c "exec 3<>/dev/tcp/$1/445" 2>/dev/null; }

ONLINE=0
HOST="${CANDIDATES[0]}"
ADDR="$HOST"
for cand in "${CANDIDATES[@]}"; do
    addr="$(resolve "$cand")"
    [ -n "$addr" ] || addr="$cand"
    if top_up "$addr"; then
        HOST="$cand"; ADDR="$addr"; ONLINE=1
        [ "$cand" = "${CANDIDATES[0]}" ] || say "reaching top as '$cand'"
        break
    fi
done
[ "$ONLINE" = 1 ] || say "top unreachable (tried: ${CANDIDATES[*]}) — starting offline against the local database"

if [ "$ONLINE" = 1 ]; then
    # Touch the path to fire the systemd automount (fstab: noauto,
    # x-systemd.automount). Failure here is not fatal: the app degrades.
    if ! timeout 10 ls "$MOUNT" >/dev/null 2>&1; then
        say "share did not mount at $MOUNT — tracks will show unavailable"
    fi

    # Metadata first and synchronously: it is ~17 MB, rsync-delta, and the app
    # reads it at startup.
    # NB `--host` is a GLOBAL option on dbsync's parser, so it goes BEFORE the
    # subcommand. After it argparse rejects the whole invocation with
    # "unrecognized arguments" — which this script then reported as the far
    # more innocent-sounding "db pull failed (continuing)".
    "$PY" "$DBSYNC" --host "$HOST" pull || say "db pull failed (continuing)"

    # Art: thumbs (~21 MB) block launch because the album grid is the first
    # thing you see; the full-size covers (~192 MB) trickle in behind it, since
    # only the now-playing view wants them.
    # Same first-contact rule as dbsync's SSH: a new name (top vs top.local)
    # must not wedge on the host-key prompt, a changed key must still fail.
    RSH="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
    mkdir -p "$ART_LOCAL"
    rsync -a -e "$RSH" --timeout=20 --include='*-t.jpg' --exclude='*' \
        "$HOST:.cache/player/art/" "$ART_LOCAL/" 2>/dev/null \
        || say "thumb sync failed (covers may be blank)"
    ( rsync -a -e "$RSH" --timeout=60 --include='*-f.jpg' --exclude='*' \
        "$HOST:.cache/player/art/" "$ART_LOCAL/" >/dev/null 2>&1 ) &
fi

# ---- guardrails on air ----------------------------------------------------
# top owns writes to the FILES and does them locally at full speed. Neither
# machine should be rewriting tags or embedding lyrics across 208 GB of SMB, so
# pin both off here on every launch rather than trusting a synced pref.
"$PY" - "$PREFS" <<'EOF' 2>/dev/null || true
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
d = {}
if p.exists():
    try:
        d = json.loads(p.read_text())
    except ValueError:
        d = {}
if d.get("tagWrites") == "on" or d.get("lyricsEmbed", True):
    d["tagWrites"] = "log" if d.get("tagWrites") != "off" else "off"
    d["lyricsEmbed"] = False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))
EOF

# ---- run ------------------------------------------------------------------
"$PY" "$MAIN" "$@"
rc=$?

# ---- push what this session changed ---------------------------------------
if [ "$ONLINE" = 1 ] && top_up "$ADDR"; then
    "$PY" "$DBSYNC" --host "$HOST" push || say "db push failed — ratings stay local until the next sync"
fi
exit $rc
