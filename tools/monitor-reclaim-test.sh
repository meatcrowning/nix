#!/usr/bin/env bash
# Does a window come back when the screen does?
#
# WHAT THIS IS FOR
#
# Powering the display off drops its DisplayPort link entirely, so Hyprland
# destroys the output and re-adds it when the screen wakes (measured on `top`
# 2026-08-01, in the compositor's own log). This desktop is every-window-
# floating on one workspace, so windows carry absolute coordinates across that
# gap and come back at coordinates that are no longer on any screen: running,
# listed, focusable, invisible. `hyprland.lua`'s `monitor.added` handler puts
# them back. This checks that it does, and — just as important — that it leaves
# alone a window that is already where he put it.
#
# WHY THERE IS NO COMPOSITOR HERE
#
# The obvious harness is a nested Hyprland with a headless output that gets
# removed and re-added. It is the wrong tool: the interesting half of this
# change is arithmetic and the decision of what to touch, and to reach it you
# would have to reproduce a monitor loss, which is exactly the operation that
# migrates windows onto a REAL monitor if anything about the nesting is off.
# So instead the handler is run for real — the actual source lines, extracted
# from `hyprland.lua` between its `monitor-reclaim` markers — against a stubbed
# `hl`. Everything the handler touches is a function on that table, so the whole
# thing (event registration, the deferred timer, re-resolving the monitor by
# name, the panel reserve, the clamp) executes end to end with nothing running.
#
# Re-run it after touching that block, or after the marker comments move.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../home/prog/hypr-files/hyprland.lua"
RUN="$(mktemp -d)"
trap 'rm -rf "$RUN"' EXIT INT TERM

LUA="$(command -v lua || command -v lua5.4 || true)"
if [ -z "$LUA" ]; then
  # No lua in PATH is the normal case here; nothing in this repo needs one at
  # runtime. Fetch the same interpreter the flake would.
  LUA="$(nix build --no-link --print-out-paths nixpkgs#lua5_4 2>/dev/null)/bin/lua"
fi
[ -x "$LUA" ] || { echo "FAIL: no lua interpreter available"; exit 1; }

# ---- the block under test, taken from the real config ------------------------
awk '/^-- >>> monitor-reclaim >>>/{f=1} f{print} /^-- <<< monitor-reclaim <<</{f=0}' \
    "$SRC" > "$RUN/block.lua"
if [ ! -s "$RUN/block.lua" ]; then
  echo "FAIL: could not extract the monitor-reclaim block from $SRC"
  echo "      (did the >>> monitor-reclaim >>> / <<< monitor-reclaim <<< markers move?)"
  exit 1
fi
grep -q 'hl.on("monitor.added"' "$RUN/block.lua" || {
  echo "FAIL: extracted block does not register monitor.added - markers are wrong"; exit 1; }

cat > "$RUN/test.lua" <<'LUA'
local FAIL = 0
local function ok(cond, what, extra)
    if cond then print("  ok   " .. what)
    else FAIL = FAIL + 1; print("  FAIL " .. what .. (extra and ("  -> " .. extra) or "")) end
end

-- ---- the stub compositor ---------------------------------------------------
-- Only what the handler actually reaches for. Anything it calls that is not
-- here is a bug in the stub, and shows up as a lua error rather than a pass.
local S = { monitors = {}, windows = {}, layers = {}, moves = {}, timers = {}, events = {} }

hl = {
    get_monitors = function() return S.monitors end,
    get_windows  = function() return S.windows end,
    get_layers   = function() return S.layers end,
    on    = function(name, fn) S.events[name] = fn end,
    timer = function(fn, opts) table.insert(S.timers, { fn = fn, timeout = opts.timeout }) end,
    dispatch = function(d) table.insert(S.moves, d) end,
    dsp = { window = { move = function(t) return t end } },
}

local function mon(name, x, y, w, h)
    return { name = name, x = x, y = y, width = w, height = h }
end
local function win(class, ax, ay, sx, sy, monitor, floating, mapped)
    return {
        class = class, at = { x = ax, y = ay }, size = { x = sx, y = sy },
        monitor = monitor,
        floating = (floating ~= false), mapped = (mapped ~= false),
    }
end
-- The panel: a qs-bar layer on the right edge. Its WIDTH is what the handler
-- subtracts (wider than the true reserve, deliberately).
local function bar(monitor, x, w) return { namespace = "qs-bar", x = x, w = w, monitor = monitor } end

local function fire(m)
    S.moves, S.timers = {}, {}
    S.events["monitor.added"](m)
    -- the handler defers; run what it scheduled
    for _, t in ipairs(S.timers) do t.fn() end
end

dofile(BLOCK)

-- ---------------------------------------------------------------------------
print("the handler registers itself")
ok(S.events["monitor.added"] ~= nil, "monitor.added is subscribed")

-- ---------------------------------------------------------------------------
print("\nit waits for the panel before it measures")
local M = mon("DP-5", 0, 0, 1920, 1080)
S.monitors, S.layers, S.windows = { M }, { bar(M, 1286, 634) }, {}
S.moves, S.timers = {}, {}
S.events["monitor.added"](M)
ok(#S.timers == 1, "the work is deferred, not done on the event frame")
ok(#S.timers == 1 and S.timers[1].timeout >= 500,
   "...by long enough for the panel to re-anchor its layer",
   #S.timers == 1 and tostring(S.timers[1].timeout) or "no timer")
ok(#S.moves == 0, "...and nothing has moved yet")

-- ---------------------------------------------------------------------------
print("\na window left off-screen comes back")
local w = win("kitty", 4000, 3000, 507, 806, M)
S.windows = { w }
fire(M)
ok(#S.moves == 1, "the displaced window is moved", "moves=" .. #S.moves)
if #S.moves == 1 then
    local m = S.moves[1]
    ok(m.window == w, "...the move names THAT window, never the focused one")
    ok(m.x >= 0 and m.y >= 0, "...to a position on the monitor", ("x=%s y=%s"):format(m.x, m.y))
    ok(m.x + w.size.x <= 1920 - 634, "...fully clear of the panel",
       ("right edge %s vs usable %s"):format(m.x + w.size.x, 1920 - 634))
    ok(m.y + w.size.y <= 1080, "...and fully on the screen vertically",
       ("bottom %s"):format(m.y + w.size.y))
end

-- ---------------------------------------------------------------------------
print("\na window he left where he wanted it is NOT touched")
-- His real surfer geometry. Its right edge (1414) is past the panel LAYER's
-- left edge (1286) and short of the true reserve (1544) - i.e. exactly the
-- window that an over-eager "keep clear of the panel" rule rearranges on every
-- wake. It is on screen; it does not move.
S.windows = { win("surfer", 344, 61, 1070, 681, M) }
fire(M)
ok(#S.moves == 0, "a window inside the usable area is left exactly alone",
   "moves=" .. #S.moves)

S.windows = { win("hangs-off-bottom", 300, 900, 600, 500, M) }
fire(M)
ok(#S.moves == 0, "a window he deliberately hung off an edge is left alone",
   "moves=" .. #S.moves)

S.windows = { win("barely-on", 1900, 1060, 600, 500, M) }
fire(M)
ok(#S.moves == 1, "...but one with only a corner left showing IS recovered",
   "moves=" .. #S.moves)

-- negative coordinates are the other half of off-screen
S.windows = { win("board", -900, -400, 882, 880, M) }
fire(M)
ok(#S.moves == 1, "a window off the TOP-LEFT is recovered too")
if #S.moves == 1 then
    ok(S.moves[1].x >= 0 and S.moves[1].y >= 0, "...to non-negative coordinates",
       ("x=%s y=%s"):format(S.moves[1].x, S.moves[1].y))
end

-- ---------------------------------------------------------------------------
print("\nit only touches what it should")
S.windows = {
    win("tiled",    5000, 5000, 400, 400, M, false),        -- not floating
    win("unmapped", 5000, 5000, 400, 400, M, true, false),  -- not mapped
    win("elsewhere", 5000, 5000, 400, 400, mon("HDMI-A-2", 0, 0, 1920, 1080)),
}
fire(M)
ok(#S.moves == 0,
   "tiled, unmapped and other-monitor windows are all skipped", "moves=" .. #S.moves)

-- ---------------------------------------------------------------------------
print("\na window bigger than the screen still lands somewhere reachable")
S.windows = { win("huge", 9000, 9000, 4000, 4000, M) }
fire(M)
ok(#S.moves == 1, "an oversized window is still recovered")
if #S.moves == 1 then
    ok(S.moves[1].x == 0 and S.moves[1].y == 0,
       "...pinned to the monitor origin, so its top-left is grabbable",
       ("x=%s y=%s"):format(S.moves[1].x, S.moves[1].y))
end

-- ---------------------------------------------------------------------------
print("\nwith no panel up it still uses the whole screen, not a negative one")
S.layers = {}
S.windows = { win("kitty", 4000, 3000, 507, 806, M) }
fire(M)
ok(#S.moves == 1, "the window is recovered with no qs-bar layer present")
if #S.moves == 1 then
    ok(S.moves[1].x + 507 <= 1920 and S.moves[1].x >= 0,
       "...inside the full monitor width", ("x=%s"):format(S.moves[1].x))
end

-- ---------------------------------------------------------------------------
print("\nan output that vanished again before the timer ran is a no-op")
S.layers = { bar(M, 1286, 634) }
S.windows = { win("kitty", 4000, 3000, 507, 806, M) }
S.moves, S.timers = {}, {}
S.events["monitor.added"](M)
S.monitors = {}                     -- gone by the time the timer fires
for _, t in ipairs(S.timers) do t.fn() end
ok(#S.moves == 0, "nothing is moved onto a monitor that is no longer there",
   "moves=" .. #S.moves)

print("")
if FAIL == 0 then print("all monitor-reclaim assertions passed"); os.exit(0)
else print(FAIL .. " FAILED"); os.exit(1) end
LUA

"$LUA" -e "BLOCK='$RUN/block.lua'" "$RUN/test.lua"
