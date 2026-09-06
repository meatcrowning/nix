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
# REACHING TOP IS A PRECONDITION, NOT A NICETY. This used to degrade: if top was
# asleep the player still opened, against the local database, with every track
# marked unavailable. That is a worse experience than not opening — a window
# full of music that cannot play, and no statement anywhere of why. So the two
# checks that decide whether there IS a library (top answers on :445, and the
# share actually mounted) are now fatal: say so in a desktop notification and
# exit without starting the app.
#
# Escape hatch: PLAYER_OFFLINE=1 restores the old degrade-and-launch behaviour,
# for looking at metadata (ratings, lyrics, play counts) with no library
# present. Nothing on the happy path changes. See docs/agents/air-library-share.md.
#
# Only ever invoked on air (home/prog/player.nix picks it for host == "air").
# On top the library is local and none of this exists — player.nix runs main.py
# directly there, so there is no reachability check to get wrong.
set -uo pipefail

# Names for top, tried in order. `top` FIRST, and it is worth five seconds of
# every launch: measured on book 2026-08-04, resolving `top.local` takes ~5s
# (mDNS, after the other resolvers time out) against 0.04s for `top`, which the
# LAN's own DNS answers at home and tailscale's MagicDNS answers off it. The
# mDNS name stays as the fallback for a network where neither knows it.
# PLAYER_SYNC_HOST pins the list to one name.
if [ -n "${PLAYER_SYNC_HOST:-}" ]; then
    CANDIDATES=("$PLAYER_SYNC_HOST")
else
    CANDIDATES=(top top.local)
fi
MOUNT="/run/media/lam/SSD/aud"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN="$HERE/../main.py"
DBSYNC="$HERE/dbsync.py"
ART_LOCAL="${XDG_CACHE_HOME:-$HOME/.cache}/player/art"
PREFS="${XDG_STATE_HOME:-$HOME/.local/state}/player/prefs.json"
PY="${PLAYER_PYTHON:-/usr/bin/python3}"

# ssh connection multiplexing. dbsync and the two art rsyncs are four separate
# ssh invocations, each otherwise paying a full TCP + key-exchange + auth
# handshake (~0.17s on this LAN, and it is ~0.28s cold). Naming one control
# socket here — and handing the same name to dbsync.py through the env — makes
# the first connection a master that the rest ride on, measured at ~0.05s each.
# %C is a hash of (host, port, user), so top.local and top can't collide.
# ControlPersist lets the master outlive this script's first ssh but not the
# session; nothing needs cleaning up.
export PLAYER_SSH_CONTROL="${XDG_RUNTIME_DIR:-/tmp}/player-dbsync-ssh-%C"
SSH_MUX=(-o ControlMaster=auto -o ControlPersist=30
         -o "ControlPath=$PLAYER_SSH_CONTROL")

say() { printf 'player: %s\n' "$*" >&2; }

# Fatal, with somewhere the message can actually be SEEN: the player is started
# from the runner, so stderr goes nowhere a person is looking. notify-send is
# how the rest of this desktop talks (surfer's toasts go the same way); the
# stderr copy is for when it's run from a terminal.
die_ui() {
    say "$1"
    command -v notify-send >/dev/null 2>&1 &&
        notify-send -a player -u critical -i audio-x-generic "player" "$1" || true
    exit 1
}

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

# ---- the share, and healing it --------------------------------------------
# top answering on :445 is not the same as the share being usable, and
# "usable" is not the same as "mounted". THE recurring failure here is a mount
# that IS mounted — active per systemd, present in /proc/mounts, 25h uptime —
# and dead: the SMB session died under a suspend or a network change, so every
# access returns ESTALE ("Stale file handle"), instantly. The automount cannot
# rescue that, because from systemd's side the unit is already up, so nothing
# ever re-triggers it. Measured on book 2026-08-20.
#
# So don't diagnose, RECOVER. Restarting the fstab-generated .mount unit
# unmounts and remounts it, takes ~1s, and needs no root and no polkit prompt
# (verified on book). This is the general rule the launcher had been missing
# and getting patched for: a precondition the launcher can restore itself is
# not something to stop and tell him about. Only what survives the repair is.
MOUNT_UNIT="$(systemd-escape -p --suffix=mount "$MOUNT" 2>/dev/null)"

# Covers all three shapes at once: never mounted (automount fires), stale
# (rc!=0 in milliseconds), and hung (killed by the timeout).
share_ok() { timeout 10 ls "$MOUNT" >/dev/null 2>&1; }

share_heal() {
    [ -n "$MOUNT_UNIT" ] || return 1
    say "share at $MOUNT is not usable — remounting $MOUNT_UNIT"
    timeout 30 systemctl restart "$MOUNT_UNIT" >/dev/null 2>&1 || return 1
    share_ok
}

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
# No top means no library, so stop here and SAY so rather than opening a window
# full of unplayable tracks. PLAYER_OFFLINE=1 opts back into degrading.
if [ "$ONLINE" != 1 ]; then
    if [ -z "${PLAYER_OFFLINE:-}" ]; then
        die_ui "can't reach top (tried: ${CANDIDATES[*]}) — the music lives there, so there is nothing to play. Wake it or join the tailnet, then try again."
    fi
    say "top unreachable (tried: ${CANDIDATES[*]}) — PLAYER_OFFLINE set, starting against the local database"
fi

if [ "$ONLINE" = 1 ]; then
    # Touch the path to fire the systemd automount (fstab: noauto,
    # x-systemd.automount), and remount it if what is there is dead. A share
    # that is still unusable after the repair leaves every track unavailable,
    # which is the same non-experience as top being down, so it gets the same
    # treatment. See share_ok/share_heal above for why the repair exists.
    if ! share_ok && ! share_heal; then
        if [ -z "${PLAYER_OFFLINE:-}" ]; then
            die_ui "top is up but the library share at $MOUNT is down and would not remount — nothing would be playable. Check that top is still sharing aud, then try again."
        fi
        say "share unusable at $MOUNT — tracks will show unavailable"
    fi

    # Metadata first and synchronously: it is ~17 MB, rsync-delta, and the app
    # reads it at startup.
    # NB `--host` is a GLOBAL option on dbsync's parser, so it goes BEFORE the
    # subcommand. After it argparse rejects the whole invocation with
    # "unrecognized arguments" — which this script then reported as the far
    # more innocent-sounding "db pull failed (continuing)".
    "$PY" "$DBSYNC" --host "$HOST" pull || say "db pull failed (continuing)"

    # Art: a FIRST cache fill blocks, because an empty album grid is not an
    # honest first frame. Once air already has thumbnails, though, refreshing
    # its ~21 MB cache before every launch delays a fully usable player by
    # 15 seconds on this Wi-Fi link. Existing art remains valid while rsync
    # refreshes in the background; a new thumb simply appears on the next
    # ordinary relaunch, like the full-size covers (~192 MB).
    # Same first-contact rule as dbsync's SSH: a new name (top vs top.local)
    # must not wedge on the host-key prompt, a changed key must still fail.
    # SSH_MUX rides the connection dbsync just opened instead of building a
    # third and fourth of its own.
    RSH="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new ${SSH_MUX[*]}"
    mkdir -p "$ART_LOCAL"
    thumb_sync() {
        rsync -a -e "$RSH" --timeout=20 --include='*-t.jpg' --exclude='*' \
            "$HOST:.cache/player/art/" "$ART_LOCAL/" 2>/dev/null \
            || say "thumb sync failed (covers may be blank)"
    }
    if find "$ART_LOCAL" -maxdepth 1 -type f -name '*-t.jpg' -print -quit | grep -q .; then
        thumb_sync &
    else
        thumb_sync
    fi
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
