#!/bin/sh
# leak-check.sh — did a test leak into the user's live session?
#
# The enforcement half of AGENTS.md -> "Testing without interfering with the
# user". That rule is otherwise kept by discipline alone, and on 2026-07-30 it
# was not kept: workers took his keyboard and pointer focus while he was using
# the machine. This script cannot stop a test from grabbing focus, but it does
# catch the *residue* every leaked test leaves behind, at the one moment every
# agent here is already required to pass through: preflight.
#
# Six states, all of them things a harness is supposed to have cleaned up:
#   1. The systemd user manager pointing at a compositor that is not his
#      (hypr-session-env.sh --check — reused, never reimplemented; the full
#      story of why that store goes wrong is in AGENTS.md under
#      home/srvs/hypr-env.nix).
#   2. $XDG_RUNTIME_DIR/hypr/<sig>/ lock directories whose PID is dead.
#   3. A second, live Hyprland that is not the session one — a nested test
#      compositor still running, still able to hold a seat and a clipboard.
#   4. A sandbox monitor left standing (/tmp/vtb-sandbox), i.e. `sandbox.sh
#      start` without its `stop`.
#   5. A TEST WINDOW ON HIS REAL MONITOR — a sandbox-tagged (or probe-titled)
#      client that is not on a HEADLESS-* output. Added 2026-07-30, because 1-4
#      caught only residue and he was reporting the live symptom: "test windows
#      keep popping up".
#   6. HIS SEAT LEFT SOMEWHERE HE DID NOT PUT IT — keyboard focus on a test
#      window or on an off-screen monitor, or the pointer parked inside a
#      HEADLESS-* output. Same report: "they keep moving my mouse around". A
#      cursor on a monitor with no cable in it is not a state a real session
#      reaches by itself. Since 2026-07-30 it also NOTES a pointer sitting on
#      the exact centre of a real monitor — where Hyprland snaps it when an
#      output is removed, which is what "the mouse randomly moves to the centre
#      of the screen" turned out to be. tools/sandbox.sh now undoes that snap
#      (sg_pointer_pin); the note catches a harness that does not.
#
# WARNS ONLY, AND MUST STAY THAT WAY. Every one of these states is one a real
# login can legitimately be in — he starts nested compositors himself, and a
# TTY has no session at all. Blocking his rebuild on a false positive is worse
# than the bug this exists to catch, so preflight ignores the exit status.
# Exit 1 means "found something" for any other caller that wants it.
set -u

found=0
warn() { found=1; printf '%s\n' "$@"; }

HYPR_ROOT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr"
ENVCHK="$HOME/.config/scripts/hypr-session-env.sh"
REPAIR="  repair:  $ENVCHK --restore"

# 1. Manager environment. rc 1 = drift; rc 3 = no live Hyprland (TTY, ssh,
#    another session type) and is not a fault.
live_sig=""
if [ -x "$ENVCHK" ]; then
  out=$("$ENVCHK" --check 2>&1); rc=$?
  [ "$rc" -eq 1 ] && warn "WARN: leaked test - $out"
  live_sig=$("$ENVCHK" --print 2>/dev/null | sed -n 's/^HYPRLAND_INSTANCE_SIGNATURE=//p')
fi

# 2 + 3. Lock directories: dead PID = a compositor that was SIGKILLed and never
#        cleaned up after; live PID that is not the session's = one still running.
for d in "$HYPR_ROOT"/*/; do
  [ -f "$d/hyprland.lock" ] || continue
  sig=$(basename "$d")
  pid=$(sed -n 1p "$d/hyprland.lock" 2>/dev/null)
  wl=$(sed -n 2p "$d/hyprland.lock" 2>/dev/null)
  case "$pid" in ''|*[!0-9]*) continue ;; esac
  if ! kill -0 "$pid" 2>/dev/null; then
    warn "WARN: dead compositor lock left behind: $d (pid $pid, ${wl:-?})" \
         "      A nested test compositor was killed without tearing down." \
         "      Safe to remove once nothing points at it:  rm -rf $d" \
         "$REPAIR"
  elif [ -n "$live_sig" ] && [ "$sig" != "$live_sig" ]; then
    warn "WARN: a second Hyprland is RUNNING: pid $pid on ${wl:-?} (not his session)." \
         "      If that is a test compositor, stop it - while it lives it owns a" \
         "      seat, a clipboard and this manager's environment." \
         "$REPAIR"
  fi
done

# 4. Sandbox left standing. The monitor is the part that matters — a HEADLESS-*
#    output in his live compositor is a test that never tore down — so it is
#    reported separately from the directory, which may just be litter (or a
#    sandbox another agent is using right now).
SBOX="${VTB_SANDBOX_DIR:-/tmp/vtb-sandbox}"
if hyprctl version >/dev/null 2>&1; then
  heads=$(hyprctl monitors -j 2>/dev/null | sed -n 's/.*"name": "\(HEADLESS-[0-9]*\)".*/\1/p')
  [ -n "$heads" ] && warn \
    "WARN: headless sandbox monitor(s) still in his live compositor: $heads" \
    "      A 'sandbox.sh start' with no 'stop'. Windows may still be on it." \
    "      repair:  $HOME/nix/tools/sandbox.sh stop"
fi
# The STATE FILE, not the directory. `stop` removes state+classes and leaves the
# (now empty) directory behind, so testing for the directory made a cleanly
# stopped sandbox warn on every preflight from then until a reboot cleared /tmp —
# a permanent false positive that teaches agents to skim past this whole script.
# `start` writes the state file and `stop` removes it, so it is the honest
# marker of "a sandbox is up"; the monitor half is caught separately above.
if [ -f "$SBOX/state" ] && [ -z "${heads:-}" ]; then
  warn "WARN: sandbox state left behind at $SBOX/state (no headless monitor, so" \
       "      the monitor half was torn down).  repair:  $HOME/nix/tools/sandbox.sh stop"
fi

# 5 + 6. The live symptoms, not the residue: a test window he can SEE, and his
#        seat left where a harness put it. One python call over three hyprctl
#        reads (~30ms total) — this runs inside preflight, so it stays cheap and
#        it stays read-only.
if hyprctl version >/dev/null 2>&1; then
  seat=$(python3 - <<'PY' 2>/dev/null
import json, subprocess
def j(*a):
    return json.loads(subprocess.check_output(["hyprctl", "-j", *a]))
try:
    mons = j("monitors")
    clients = j("clients")
    active = j("activewindow")
except Exception:
    raise SystemExit(0)
byid = {m["id"]: m for m in mons}
head = lambda mid: byid.get(mid, {}).get("name", "").startswith("HEADLESS-")

def owned(c):
    tags = [t.rstrip("*") for t in c.get("tags") or []]
    if "sandbox" in tags:
        return "tagged sandbox"
    # tools/vtb-*-test.sh name their probe windows *PROBE; a real app of his
    # does not. Cheap second net for a client that lost its tag (a rule that
    # did not match, a window re-created by the client).
    if "PROBE" in (c.get("title") or "") or "PROBE" in (c.get("initialTitle") or ""):
        return "probe-titled"
    return None

for c in clients:
    why = owned(c)
    if why and not head(c.get("monitor")):
        mon = byid.get(c.get("monitor"), {}).get("name", "?")
        print("VISIBLE\t%s\t%s\t%s\t%s" % (
            c["address"], c.get("class") or "?", mon, why))

addr = active.get("address") or ""
if addr:
    for c in clients:
        if c["address"] != addr:
            continue
        if owned(c):
            print("FOCUS\ttest window %s (%s)" % (addr, c.get("class") or "?"))
        elif head(c.get("monitor")):
            print("FOCUS\t%s, which is on an off-screen monitor"
                  % (c.get("class") or addr))

try:
    x, y = (int(v) for v in subprocess.check_output(
        ["hyprctl", "cursorpos"]).decode().split(","))
except Exception:
    x = y = None
if x is not None:
    for m in mons:
        if not m["name"].startswith("HEADLESS-"):
            continue
        if m["x"] <= x < m["x"] + m["width"] and m["y"] <= y < m["y"] + m["height"]:
            print("POINTER\t%d,%d is inside %s" % (x, y, m["name"]))
    # The AFTER-THE-FACT warp signature. CMonitor::onDisconnect snaps the cursor
    # to exactly the centre of the surviving monitor, so a pointer sitting on
    # that one pixel is very likely an output removal that did not go through
    # sg_pointer_pin. He can of course park it there himself, which is why this
    # only ever warns.
    for m in mons:
        if m["name"].startswith("HEADLESS-"):
            continue
        if (x, y) == (m["x"] + m["width"] // 2, m["y"] + m["height"] // 2):
            print("SNAP\t%d,%d is the exact centre of %s" % (x, y, m["name"]))
PY
)
  vis=$(printf '%s\n' "$seat" | sed -n 's/^VISIBLE\t//p')
  if [ -n "$vis" ]; then
    warn "WARN: a TEST WINDOW is on a monitor he can see:"
    printf '%s\n' "$vis" | sed 's/^/        /'
    warn "      A harness put a window in front of him and did not take it away." \
         "      repair:  $HOME/nix/tools/sandbox.sh stop   (closes tagged windows" \
         "               wherever they ended up), or close it by hand."
  fi
  foc=$(printf '%s\n' "$seat" | sed -n 's/^FOCUS\t//p')
  [ -n "$foc" ] && warn \
    "WARN: his keyboard focus is on $foc." \
    "      A harness took the seat and never gave it back. Nothing to repair" \
    "      from here - click where you meant to be - but the harness that did" \
    "      it is the bug: AGENTS.md -> Testing without interfering with the user."
  ptr=$(printf '%s\n' "$seat" | sed -n 's/^POINTER\t//p')
  [ -n "$ptr" ] && warn \
    "WARN: the pointer is parked off-screen: $ptr" \
    "      No session reaches that by itself, so something WARPED it. Find the" \
    "      harness that moves the cursor and delete that line; nothing under" \
    "      tools/ is allowed to."
  snap=$(printf '%s\n' "$seat" | sed -n 's/^SNAP\t//p')
  [ -n "$snap" ] && warn \
    "NOTE: the pointer is at a monitor centre: $snap" \
    "      That is where Hyprland snaps it when an output is REMOVED, so it may" \
    "      be a harness that tore a sandbox down without tools/lib/session-guard.sh's" \
    "      sg_pointer_pin. It is also just a place a pointer can be - hence NOTE."
fi

exit "$found"
