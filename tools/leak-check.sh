#!/bin/sh
# leak-check.sh — warn about test residue in the live session. It is run by
# preflight and checks six states: stale manager environment; dead compositor
# locks; a second live Hyprland; a live HEADLESS-* sandbox or stale state file;
# tagged/probe windows on visible monitors; and focus/pointer left on test or
# headless objects. It also notes the exact monitor-centre signature of an
# unpinned output-removal warp.
#
# This must remain warn-only: all states can be legitimate during a real login,
# TTY, or user-run nested compositor. Exit 1 reports findings to other callers;
# preflight ignores it. Repair hints are emitted with each finding.
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

# 4. A live HEADLESS-* output is an un-torn-down sandbox; report it separately
#    from the directory, which may be harmless litter or another active run.
SBOX="${VTB_SANDBOX_DIR:-/tmp/vtb-sandbox}"
if hyprctl version >/dev/null 2>&1; then
  heads=$(hyprctl monitors -j 2>/dev/null | sed -n 's/.*"name": "\(HEADLESS-[0-9]*\)".*/\1/p')
  [ -n "$heads" ] && warn \
    "WARN: headless sandbox monitor(s) still in his live compositor: $heads" \
    "      A 'sandbox.sh start' with no 'stop'. Windows may still be on it." \
    "      repair:  $HOME/nix/tools/sandbox.sh stop"
fi
# Check the state file, not the directory: `stop` removes state and classes but
# intentionally leaves the empty directory. The monitor is checked above.
if [ -f "$SBOX/state" ] && [ -z "${heads:-}" ]; then
  warn "WARN: sandbox state left behind at $SBOX/state (no headless monitor, so" \
       "      the monitor half was torn down).  repair:  $HOME/nix/tools/sandbox.sh stop"
fi

# 5 + 6. One read-only Python probe checks visible test windows and seat residue
#        (focus, headless pointer, and centre-snap note) cheaply in preflight.
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
