-- Refer to the wiki for more information.
-- https://wiki.hypr.land/Configuring/Start/

------------------
---- MONITORS ----
------------------

-- See https://wiki.hypr.land/Configuring/Basics/Monitors/
-- host.lua is regenerated per-host by home/prog/hypr-host.nix (this file
-- itself is only seeded once, see home/prog/hyprland.nix).
local host = dofile(os.getenv("HOME") .. "/.config/hypr/host.lua")

hl.monitor({
    output   = "",
    mode     = "preferred",
    position = "auto",
    scale    = host.scale or "1",
})

-- Windows come back when the screen does.
--
-- Powering the display off drops its DisplayPort link ENTIRELY — this is not
-- DPMS, the output is gone as far as the compositor is concerned. Measured on
-- `top` 2026-08-01 in Hyprland's own log: "Connector DP-5 disconnected" ->
-- "Disabling output DP-5" in the evening, a matching reconnect in the morning.
-- This desktop is every-window-floating on a single workspace, so those windows
-- carry absolute coordinates across the gap; the output returns and they are
-- still at coordinates that are no longer on any screen. They run, they are
-- listed, they take focus, and they cannot be seen. The only way out was to
-- close every one and open it again.
--
-- So when an output appears, put back whatever is no longer on it.
--
-- >>> monitor-reclaim >>>  tools/monitor-reclaim-test.sh EXTRACTS the block
-- between these two markers and runs it against a stubbed `hl`, so the test
-- exercises this source and not a copy of it. Keep them, and keep everything
-- between them free of anything that needs a live compositor at load time.
-- How much of a window has to be on the monitor before it counts as reachable.
-- A window hanging off an edge is a thing he does on purpose; a window with
-- nothing on screen is the bug. This is the line between them.
local HOTPLUG_MIN_VISIBLE = 64

local function hotplug_panel_width(mon)
    -- The panel occupies part of the right edge. `hl.get_monitors()` does not
    -- expose the reserved rect, so this is the qs-bar layer's own width — which
    -- is WIDER than the true reserve (634 vs 376). That is fine for choosing
    -- where to put a window and wrong for deciding whether to move one, which
    -- is why only the destination below uses it.
    local wide = 0
    for _, l in ipairs(hl.get_layers() or {}) do
        if l.namespace == "qs-bar" and l.monitor and l.monitor.name == mon.name then
            wide = math.max(wide, l.w or 0)
        end
    end
    return wide
end

local function hotplug_reclaim(mon)
    local mx, my, mw, mh = mon.x, mon.y, mon.width, mon.height
    local reserve = hotplug_panel_width(mon)
    for _, w in ipairs(hl.get_windows() or {}) do
        if w.floating and w.mapped and w.monitor and w.monitor.name == mon.name then
            local ax, ay = w.at.x, w.at.y
            local sx, sy = w.size.x, w.size.y
            -- WHETHER to move is judged against the MONITOR, never against the
            -- panel-free area: a window tucked partly under the panel is where
            -- he put it, and "recovering" it would rearrange his desktop every
            -- single time the screen wakes — a worse bug than the one this
            -- exists to fix.
            local visx = math.min(ax + sx, mx + mw) - math.max(ax, mx)
            local visy = math.min(ay + sy, my + mh) - math.max(ay, my)
            local needx = math.min(HOTPLUG_MIN_VISIBLE, sx)
            local needy = math.min(HOTPLUG_MIN_VISIBLE, sy)
            if visx < needx or visy < needy then
                -- WHERE to put it may use the panel width: land it clear of the
                -- panel when it fits there, anywhere on the monitor when it
                -- does not.
                local uw = mw - reserve
                if sx > uw then uw = mw end
                local nx = math.max(mx, math.min(ax, mx + math.max(0, uw - sx)))
                local ny = math.max(my, math.min(ay, my + math.max(0, mh - sy)))
                if nx ~= ax or ny ~= ay then
                    hl.dispatch(hl.dsp.window.move({ x = nx, y = ny, window = w }))
                end
            end
        end
    end
end

hl.on("monitor.added", function(mon)
    local name = mon and mon.name
    if not name then return end
    -- Deferred, and re-resolved by NAME rather than closing over the object:
    -- on the frame the output returns the panel has not re-anchored its layer
    -- yet, so the usable area read now would be the whole screen and every
    -- recovered window would land underneath the panel.
    hl.timer(function()
        for _, m in ipairs(hl.get_monitors() or {}) do
            if m.name == name then
                hotplug_reclaim(m)
                return
            end
        end
    end, { timeout = 1200, type = "oneshot" })
end)
-- <<< monitor-reclaim <<<

---------------------
---- MY PROGRAMS ----
---------------------

-- Set programs that you use
local terminal    = "kitty"
local fileManager = "dolphin"
local menu        = "hyprlauncher"


-------------------
---- AUTOSTART ----
-------------------

-- See https://wiki.hypr.land/Configuring/Basics/Autostart/

-- Autostart necessary processes (like notifications daemons, status bars, etc.)
-- Or execute your favorite apps at launch like this:
--
-- hl.on("hyprland.start", function ()
--   hl.exec_cmd(terminal)
--   hl.exec_cmd("nm-applet")
--   hl.exec_cmd("waybar & firefox")
-- end)

-- Quickshell vertical panel (bar + launcher + workspaces + tray + clock)
hl.on("hyprland.start", function()
    -- FIRST, before anything below: make graphical-session.target active.
    -- Nothing in a bare Hyprland session does, and units we do not own can
    -- REQUIRE it rather than merely order against it — xdg-desktop-portal has
    -- `Requisite=graphical-session.target`, which is never pulled in and cannot
    -- be started by hand, so the portal (every file picker, every screen-share)
    -- was dead for the whole session. hyprland-session.target BindsTo it; see
    -- home/srvs/hypr-session-target.nix. The explicit starts below stay: they
    -- are what makes the ordering deterministic.
    hl.exec_cmd("systemctl --user start hyprland-session.target")
    -- The panel is a systemd user service (quickshell-panel, defined in
    -- quickshell.nix) with Restart=always, so a crash, an OOM kill or a stray
    -- `qs kill` recovers on its own in ~1s instead of leaving the desktop with
    -- no panel or wallpaper. reset-failed clears any StartLimit state left by
    -- the previous session's teardown before starting. QS_NO_RELOAD_POPUP (we
    -- toast reloads ourselves — see shell.qml) is set in the service's env.
    hl.exec_cmd("sh -c 'systemctl --user reset-failed quickshell-panel.service 2>/dev/null; exec systemctl --user start quickshell-panel.service'")
    -- Idle daemon: locks after 5 min / before sleep, blanks the screen.
    -- See ~/.config/hypr/hypridle.conf.
    hl.exec_cmd("hypridle")
    -- Polkit authentication agent. Plasma autostarts this itself; Hyprland
    -- doesn't, so without it any polkit-gated action (loginctl
    -- terminate-session for the power menu's logout, NetworkManager admin
    -- actions, udisks mounts, etc.) hangs forever waiting on an
    -- authorization prompt nothing is running to show.
    hl.exec_cmd("polkit-kde-agent-1")
    -- Resolve the current wallpaper (the panel draws it) and recolour the panel,
    -- kitty and this border from it. See ~/.config/scripts/wal-set.sh.
    hl.exec_cmd("$HOME/.config/scripts/wal-set.sh")
    -- Point KDE's own "the web browser" key (kdeglobals BrowserApplication) at
    -- surfer for THIS session; the Plasma session's autostart points it at
    -- vivaldi instead. Everything else that differs between the two sessions is
    -- decided by a file each reads on its own (kde-mimeapps.list, kdeglobals) —
    -- this one key has no per-session variant, so it is written at login.
    -- See home/prog/mime-defaults.nix.
    hl.exec_cmd("desktop-session-defaults")
    -- Give the systemd user manager this session's env so wal-set.service
    -- (fired by wal-set.path when wall.png changes) can talk to hyprctl,
    -- then make sure that watcher is running.
    hl.exec_cmd("systemctl --user import-environment HYPRLAND_INSTANCE_SIGNATURE WAYLAND_DISPLAY XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP PATH")
    -- import-environment above only reaches systemd user units; xdg-desktop-
    -- portal and its backends are D-Bus-activated, so they need the session
    -- env in the *dbus* activation store too — otherwise the hyprland portal
    -- can spawn without HYPRLAND_INSTANCE_SIGNATURE and screen-share fails.
    hl.exec_cmd("dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP HYPRLAND_INSTANCE_SIGNATURE")
    hl.exec_cmd("systemctl --user start wal-set.path")
    -- Grey unfocused kitty terminals to match filer / the hyprvtb inactive
    -- tone. kitty can't self-detect OS focus under Hyprland, so this listens to
    -- the event socket and drives `kitty @ set-colors` (see kitty-focus-dim.py).
    hl.exec_cmd("python3 $HOME/.config/kitty/kitty-focus-dim.py")
    -- Same for wal-prepare.path, which pre-caches tile/theme data for every
    -- image under ~/Pictures/wall as soon as it's added — see
    -- scripts/wal-prepare.sh — so WallpaperPicker.qml flips land fast. Also
    -- backfill anything already in that directory from before this existed.
    hl.exec_cmd("systemctl --user start wal-prepare.path")
    hl.exec_cmd("$HOME/.config/scripts/wal-prepare-all.sh")
    -- Tray applets + background services. The systemd user services
    -- (easyeffects, udiskie) are WantedBy graphical-session.target, which
    -- nothing activates in a Hyprland session — start them explicitly, same
    -- as the wal path units above.
    hl.exec_cmd("nm-applet --indicator")
    hl.exec_cmd("kdeconnect-indicator")
    hl.exec_cmd("systemctl --user start easyeffects.service udiskie.service")
    -- "The other machine pushed to ~/nix" — checked here (so a boot and a plain
    -- login both count as a check), on resume, and on a slow poll; offers a
    -- toast with Pull & apply / Dismiss on it. See home/srvs/repo-updates.nix.
    hl.exec_cmd("systemctl --user start repo-updates.service")
    hl.exec_cmd("$HOME/.local/bin/wizlight-tray.py")
    -- Clipboard history: everything copied lands in cliphist's db
    -- (`cliphist list` / `cliphist decode`; picker UI is future work).
    hl.exec_cmd("wl-paste --type text --watch cliphist store")
    hl.exec_cmd("wl-paste --type image --watch cliphist store")
    -- Persist the selection so copied data survives the source app closing.
    -- Without a persist daemon the selection is owned by the copying client
    -- and vanishes the moment it exits (or races), which read as paste working
    -- only while the source app is still open. wl-clip-persist holds it instead.
    hl.exec_cmd("wl-clip-persist --clipboard regular")
    -- Vista logon sound (sound map: quickshell/Sounds.qml). Read from the
    -- Settings program's model rather than hardcoded, so `soundsEnabled`,
    -- `soundTheme` and `soundLogin` mean the same thing here as they do for
    -- every other event on that page -- soundLogin was drawn in Settings and
    -- read by nothing, because this line is the only thing that plays it and it
    -- named the file itself. Defaults on a missing key, missing file or missing
    -- jq, so the sound can never be lost to a bad read.
    hl.exec_cmd([[sh -c 'S="$HOME/.config/quickshell/settings.json"; [ "$(jq -r .soundsEnabled "$S" 2>/dev/null)" = false ] && exit 0; t=$(jq -r .soundTheme "$S" 2>/dev/null); case "$t" in ""|null) t=vista;; esac; f=$(jq -r .soundLogin "$S" 2>/dev/null); case "$f" in ""|null) f="Windows Logon Sound.wav";; esac; exec pw-play "$HOME/.local/share/sounds/$t/$f"']])
    -- NOTE: deliberately do NOT switch to a "main" workspace here. This desktop
    -- is locked to a SINGLE workspace, and the hyprvtb plugin relaunches the
    -- saved session during config load (hl.plugin.load below) — those windows
    -- map onto the default workspace 1. An async `focus workspace 50` used to
    -- run here and race that mapping: windows that mapped before the switch
    -- stayed on 1, ones after landed on 50, so a fresh login scattered programs
    -- across two workspaces (some only reachable via their taskbar icon).
    -- Staying on workspace 1 keeps everything on the one workspace.
end)

-- Compositor-drawn vertical titlebars (close / maximize / rotated title,
-- right edge of every window): the hyprvtb plugin — C++ source in
-- ~/nix/home/prog/hyprvtb/, built by nix and symlinked to a stable path by
-- home-manager. A window decoration renders in the same frame as its window
-- (locked), which no layer-shell client could do; this replaced the old
-- quickshell titlebars and the in-compositor geometry event stream that
-- fed them.
-- Load the RESOLVED /nix/store path, not the symlink — this is what makes
-- `hyprctl reload` hot-swap a rebuilt plugin instead of needing a relog.
-- Hyprland tracks config-loaded plugins by the literal path STRING passed
-- here, and `CPluginSystem::updateConfigPlugins` early-returns unless that
-- list CHANGES between reloads. Pass the symlink and the string is constant
-- forever, so reload is a no-op and the stale .so stays mapped. Pass the
-- resolved store path and every rebuild yields a new string, so reload does
-- the swap itself: unload-old -> load-new -> re-parse (correct order, no
-- orphaned instance, no `plugin:hyprvtb:col.*` key collision).
--
-- ...and the block below is the seatbelt for that, because a hot swap runs
-- brand-new compositor code in-process: if the plugin build that was live when
-- the session died is the same one we are about to load, load the last
-- KNOWN-GOOD build instead. hypr-supervise (sys/dsk/hyprland.nix) is what
-- names the culprit: on an unclean exit it copies `loaded` to `crashed-with`
-- and restarts the compositor with this config, rather than letting Hyprland's
-- own watchdog come back in --safe-mode with no config at all. So a bad plugin
-- costs you the previous version and a breadcrumb in
-- ~/.local/state/hyprvtb/quarantined — not your desktop.
local VTB_SO    = "/home/lam/.config/hypr/plugins/libhyprvtb.so"
local VTB_STATE = os.getenv("HOME") .. "/.local/state/hyprvtb"

local function vtb_read(name)
    local f = io.open(VTB_STATE .. "/" .. name)
    if not f then return nil end
    local s = f:read("l")
    f:close()
    if not s or s == "" then return nil end
    return s
end

local function vtb_write(name, text)
    os.execute("mkdir -p " .. VTB_STATE)
    local f = io.open(VTB_STATE .. "/" .. name, "w")
    if not f then return end
    f:write(text .. "\n")
    f:close()
end

local function vtb_exists(path)
    local f = io.open(path, "r")
    if not f then return false end
    f:close()
    return true
end

local vtb_p = io.popen("readlink -f " .. VTB_SO)
local vtb_cur
if vtb_p then
    vtb_cur = vtb_p:read("l")
    vtb_p:close()
end
if not vtb_cur or vtb_cur == "" then vtb_cur = VTB_SO end

local vtb_crashed = vtb_read("crashed-with")
local vtb_prev    = vtb_read("loaded")
local vtb_good    = vtb_read("known-good")

-- The previous session ended cleanly (no crash breadcrumb), so whatever it was
-- running has earned the title.
if not vtb_crashed and vtb_prev and vtb_exists(vtb_prev) then
    vtb_good = vtb_prev
    vtb_write("known-good", vtb_prev)
end

local vtb_use = vtb_cur
if vtb_crashed == vtb_cur then
    if vtb_good and vtb_good ~= vtb_cur and vtb_exists(vtb_good) then
        vtb_use = vtb_good
        vtb_write("quarantined", vtb_cur)
    else
        vtb_use = nil -- nothing to fall back to: no titlebars, but a live session to debug in
        vtb_write("quarantined", vtb_cur .. " (no known-good build to fall back to)")
    end
end
os.remove(VTB_STATE .. "/crashed-with")

if vtb_use then
    vtb_write("loaded", vtb_use)
    hl.plugin.load(vtb_use)
else
    vtb_write("loaded", "")
end
hl.config({
    plugin = {
        hyprvtb = {
            -- colour lines rewritten by wal-set.sh alongside active_border
            ["bg_color"]          = "rgba(000000ff)",
            ["col.text"]          = "rgba(8c7138ff)",
            ["col.button_border"] = "rgba(382d16ff)",
            ["col.accent"]        = "rgba(d99c1fff)",
            ["col.bg_alt"]        = "rgba(120f08ff)",
            ["col.crit"]          = "rgba(fab424ff)",
            ["col.warn"]          = "rgba(e6c14aff)",
            -- Drop-shadow opacity — a USER setting (Settings > Appearance),
            -- persisted HERE like the colours above so a `hyprctl reload`
            -- (or a restart) keeps the chosen value instead of reverting to
            -- the C++ default 0.6. wal-set.sh rewrites this line from
            -- settings.json's shadowAlpha on every apply, and the panel
            -- (SettingsApply.qml) applies live changes over hl.config; this
            -- line is only the persisted floor. The value is masked in
            -- seed-drift.sh so the runtime rewrite is not flagged as drift.
            ["shadow_alpha"]      = 0.6,
            -- Title orientation — the other USER setting persisted here, for
            -- exactly the shadow_alpha reasons above: wal-set.sh rewrites it
            -- from settings.json's titleOrientation, the panel applies live
            -- changes, this line is the persisted floor across a reload.
            ["title_rotated"]     = false,
            -- Titlebar anchor edge + unfocus dim — two more USER keys riding
            -- this block for the shadow_alpha reason: the panel sets them live
            -- over hl.config, but a `hyprctl reload` (fired by wal-set.sh on a
            -- theme change, and by apply-pixel-font.sh on a font change) re-runs
            -- this file and drops any runtime override, so the titlebar side
            -- snapped back to the C++ default "right" and the dim toggle back to
            -- default-true on every theme tweak. apply-window-frame.sh (and
            -- wal-set.sh) rewrite these from settings.json so the pick survives.
            -- Masked in seed-drift.sh so the runtime rewrite is not flagged.
            ["titlebar_edge"]     = "right",
            ["dim_unfocused"]     = true,
            ["compact"]           = false,
            -- The desktop font pick — persisted like shadow_alpha above
            -- because this file AUTO-RELOADS: wal-set.sh seds the palette in
            -- on every theme apply, the re-run lua reverted any key living
            -- only in the runtime override, and the titlebar font reset to
            -- the C++ default on every colour tweak (found 2026-08-08).
            -- apply-pixel-font.sh rewrites these from settings.json; the
            -- values here are only the first-boot seeds.
            ["font"]              = "More Perfect DOS VGA",
            ["font_size"]         = 15,
            ["font_smooth"]       = false,
            -- THE DESKTOP'S MOTION. This is not just the window roll: the roll
            -- is the REFERENCE every sliding animation on this machine is
            -- matched to (docs/DESIGN.md 6.2), so this one number is also the
            -- quickshell panel's popups and drawers, the titlebar tooltip, and
            -- the drawers in the six apps under ~/nix/apps. The plugin writes
            -- the resolved value to ~/.local/state/hyprvtb/motion.json and the
            -- panel (ViewMode.qml) and the apps (pylib/deskstyle.py) both watch
            -- that file, so `hyprctl reload` after changing this retunes the
            -- whole desktop at once with nothing restarted.
            --
            -- Commented out because the C++ default IS 260/0.55 and this file
            -- is seed-once on both machines: a value written here would apply
            -- only to whichever copy is not stale. Uncomment to retune.
            -- slide_duration_ms  = 260,   -- 20..4000
            -- roll_slide_frac    = 0.55,  -- slide beat vs set-down beat
            -- macOS-style momentum scrolling: content keeps gliding after the
            -- fingers leave the pad, decelerating exponentially. Synthesized by
            -- the plugin at the seat, so it reaches every toolkit at once —
            -- design and provenance in docs/kinetic-scroll.md. Off by default
            -- in C++ (the blast radius is the compositor); this turns it on for
            -- real, surviving reloads and relogins, which a runtime
            -- kinetic_set(true) deliberately does not.
            --
            -- Per-host (hypr-host.nix -> host.lua): ON for air/book, whose
            -- touchpad is the only finger source either machine has; OFF on
            -- top, which drives a wheel mouse and wants the plain behaviour.
            kinetic               = host.kinetic or false,
            -- Feel, live-tunable without a reload via
            -- `hyprctl eval "hl.plugin.hyprvtb.kinetic_set('friction', X)"`:
            -- 2.6 floaty, 3.6 mac-anchored, 5.2 snappy. coast = v0/friction.
            kinetic_friction      = 3.6,
            -- Deny only clients whose wheel drives a DISCRETE, state-changing
            -- action rather than scrolling content — a coast fires those dozens
            -- of times. mpv is the live one: its builtin bindings are
            -- `add volume ±2` vertically and `seek ∓10` horizontally (verified
            -- via mpv's own input-bindings IPC property), and Fedora's mpv on
            -- book is Wayland-native (class `mpv`), so momentum does reach it.
            -- vlc (`add volume`, hotkeys-y-wheel-mode) and feh (next/prev image)
            -- are X11-only here and already excluded by kinetic_deny_xwayland,
            -- but are listed so the policy survives that default being flipped.
            -- Everything else gets momentum: viewer used to be denied because
            -- its wheel ZOOMS and was sign-only (12 events saturated 1..8); that
            -- handler is delta-proportional now, so a coast there just keeps
            -- zooming smoothly and the clamp still holds.
            kinetic_deny_classes  = "mpv,vlc,feh",
        },
    },
})


-------------------------------
---- ENVIRONMENT VARIABLES ----
-------------------------------

-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Environment-variables/

hl.env("XCURSOR_SIZE", "22")
hl.env("HYPRCURSOR_SIZE", "22")
-- Base cursor theme (~/.icons/GoogleDot-Black, from the Plasma install). This is
-- only the seed default: cursor-recolor.sh rewrites these two lines in the live
-- file to "GoogleDot-<accent>" — its copy of this theme with the white outline
-- tinted to the wallpaper accent — so a re-login loads the accent cursor
-- natively at startup (a runtime `hyprctl setcursor` that early doesn't stick).
-- On a brand-new machine, before the first wal-set.sh run, this plain black
-- outline shows until the accent copy is built. hyprcursor loads either as a
-- plain XCursor theme (neither is a native .hyprcursor theme).
hl.env("XCURSOR_THEME", "GoogleDot-Black")
hl.env("HYPRCURSOR_THEME", "GoogleDot-Black")

-- Route Qt apps through the KDE platform plugin (KDEPlasmaPlatformTheme) so
-- they read their palette, fonts and icon theme from ~/.config/kdeglobals —
-- which wal-set.sh recolours from the wallpaper and pins the pixel font into.
-- This makes non-KDE Qt apps match the KDE ones and the panel. (Was "gtk3",
-- which only gave them the GTK theme and left kdeglobals — i.e. the leftover
-- Plasma theme — driving the KDE apps.)
hl.env("QT_QPA_PLATFORMTHEME", "kde")


-----------------------
----- PERMISSIONS -----
-----------------------

-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Permissions/
-- Please note permission changes here require a Hyprland restart and are not applied on-the-fly
-- for security reasons

-- hl.config({
--   ecosystem = {
--     enforce_permissions = true,
--   },
-- })

-- hl.permission("/usr/(bin|local/bin)/grim", "screencopy", "allow")
-- hl.permission("/usr/(lib|libexec|lib64)/xdg-desktop-portal-hyprland", "screencopy", "allow")
-- hl.permission("/usr/(bin|local/bin)/hyprpm", "plugin", "allow")


-----------------------
---- LOOK AND FEEL ----
-----------------------

-- Refer to https://wiki.hypr.land/Configuring/Basics/Variables/
hl.config({
    cursor = {
        no_warps = true,
        warp_on_change_workspace = 0,
        warp_on_toggle_special = 0,
        -- Per-host (see hypr-host.nix -> host.lua): the software cursor is
        -- forced only where the hardware cursor plane misbehaves (top's NVIDIA
        -- RTX 5070 leaves a static ghost). On air (Apple/Asahi) the hardware
        -- cursor is used, because its plane updates immediately on
        -- `hyprctl setcursor` — so the wal accent re-tint shows at once instead
        -- of only after a hover (the software cursor doesn't re-rasterise the
        -- on-screen shape on a live theme change).
        no_hardware_cursors = host.no_hardware_cursors,
    },
    general = {
        gaps_in  = 5,
        gaps_out = 35,

        border_size = 2,

        col = {
	    active_border = "rgba(5c9fccee)",
            -- active_border   = { colors = {"rgba(33ccffee)", "rgba(00ff99ee)"}, angle = 45 },
            -- The unfocused-window border is the THIRD surface the "dim
            -- unfocused" pick moves (titlebar + body + border, all as one —
            -- docs/DESIGN.md §3.1.1): dim ON gives this static grey, dim OFF
            -- rewrites it to the active accent so nothing distinguishes an
            -- unfocused window. wal-set.sh (on a theme change) and
            -- apply-window-frame.sh (on the toggle) rewrite this floor from
            -- settings.json's dimUnfocused; the rgba mask in seed-drift.sh
            -- already covers the runtime value. Seed is the dim-ON grey to
            -- match dimUnfocused's default-ON.
            inactive_border = "rgba(595959aa)",
        },

        -- Click-drag any window edge to resize (also how the scratchpad
        -- terminal's width is adjusted).
        resize_on_border = true,

        -- Please see https://wiki.hypr.land/Configuring/Advanced-and-Cool/Tearing/ before you turn this on
        allow_tearing = false,

        layout = "dwindle",
    },

    decoration = {
        rounding       = 0,
        rounding_power = 2,

        -- Change transparency of focused and unfocused windows
        active_opacity   = 1.0,
        inactive_opacity = 1.0,

        -- Whole-window unfocus dim (Settings > Appearance > "dim unfocused").
        -- The hyprvtb titlebar already greys on unfocus (plugin:hyprvtb:
        -- dim_unfocused) and the Qt apps used to grey their own foregrounds to
        -- Theme.inactive as well (docs/DESIGN.md 3.1.1) — that app-side fade
        -- is RETIRED (his board call, 2026-08-09), so this native content dim
        -- is now the ONE unfocus mechanism, and it covers the windows that
        -- have no other hook: an arbitrary window's CONTENT (a browser, a
        -- terminal) never had the app fade, so its body stayed lit while its
        -- titlebar and border read unfocused. "The setting should affect the
        -- window itself, the border, EVERYTHING, not only the titlebar."
        -- Seed is ON to match plugin dim_unfocused's default-true, but this
        -- line is a persisted FLOOR that apply-window-frame.sh / wal-set.sh
        -- rewrite from settings.json's dimUnfocused (masked in seed-drift.sh):
        -- SettingsApply.qml toggles it live over hl.config when the setting
        -- flips, and the persist keeps the pick across a reload instead of
        -- reverting to default-true. Retune dim_strength — 0.5 is the default.
        dim_inactive = true,
        dim_strength = 0.5,

        -- Native soft shadow off: hyprvtb draws its own hard bottom-left drop
        -- shadow, and this blurred halo layered a faint second shadow around the
        -- whole focused frame on top of it.
        shadow = {
            enabled      = false,
            range        = 4,
            render_power = 3,
            color        = 0xee1a1a1a,
        },

        blur = {
            enabled   = true,
            size      = 3,
            passes    = 1,
            vibrancy  = 0.1696,
        },
    },

    animations = {
        enabled = true,
    },
})

-- Default curves and animations, see https://wiki.hypr.land/Configuring/Advanced-and-Cool/Animations/
hl.curve("easeOutQuint",   { type = "bezier", points = { {0.23, 1},    {0.32, 1}    } })
hl.curve("easeInOutCubic", { type = "bezier", points = { {0.65, 0.05}, {0.36, 1}    } })
hl.curve("linear",         { type = "bezier", points = { {0, 0},       {1, 1}       } })
hl.curve("almostLinear",   { type = "bezier", points = { {0.5, 0.5},   {0.75, 1}    } })
hl.curve("quick",          { type = "bezier", points = { {0.15, 0},    {0.1, 1}     } })
-- Matches Qt's Easing.OutCubic — the curve the Quickshell workspace-outline
-- slide uses — so the window slide and the panel outline slide feel identical.
hl.curve("easeOutCubic",   { type = "bezier", points = { {0.33, 1},    {0.68, 1}    } })

-- Default springs
hl.curve("easy",           { type = "spring", mass = 1, stiffness = 71.2633, dampening = 15.8273644 })

hl.animation({ leaf = "global",        enabled = true,  speed = 10,   bezier = "default" })
-- monitorAdded drives the whole-screen zoom/fade when an output appears —
-- which includes login. Off: the desktop should just BE there.
hl.animation({ leaf = "monitorAdded",  enabled = false })
hl.animation({ leaf = "border",        enabled = true,  speed = 5.39, bezier = "easeOutQuint" })
hl.animation({ leaf = "windows",       enabled = true,  speed = 4.79, spring = "easy" })
hl.animation({ leaf = "windowsIn",     enabled = true,  speed = 4.1,  spring = "easy",         style = "popin 87%" })
hl.animation({ leaf = "windowsOut",    enabled = true,  speed = 1.49, bezier = "linear",       style = "popin 87%" })
hl.animation({ leaf = "fadeIn",        enabled = true,  speed = 1.73, bezier = "almostLinear" })
hl.animation({ leaf = "fadeOut",       enabled = true,  speed = 1.46, bezier = "almostLinear" })
hl.animation({ leaf = "fade",          enabled = true,  speed = 3.03, bezier = "quick" })
hl.animation({ leaf = "layers",        enabled = true,  speed = 3.81, bezier = "easeOutQuint" })
hl.animation({ leaf = "layersIn",      enabled = true,  speed = 4,    bezier = "easeOutQuint", style = "fade" })
hl.animation({ leaf = "layersOut",     enabled = true,  speed = 1.5,  bezier = "linear",       style = "fade" })
hl.animation({ leaf = "fadeLayersIn",  enabled = true,  speed = 1.79, bezier = "almostLinear" })
hl.animation({ leaf = "fadeLayersOut", enabled = true,  speed = 1.39, bezier = "almostLinear" })
-- slidevert (not fade): the whole workspace slides VERTICALLY on a switch, so
-- the windows themselves move up/down to match the panel's vertical stack —
-- going to a higher-numbered workspace slides the view down to the one "below".
-- speed 2.2 (ds) = 220ms with easeOutCubic, identical to the Quickshell
-- workspace-outline slide (Behavior on y: 220ms, Easing.OutCubic), so the
-- windows and the panel indicator move as one.
hl.animation({ leaf = "workspaces",    enabled = true,  speed = 2.2, bezier = "easeOutCubic", style = "slidevert" })
hl.animation({ leaf = "workspacesIn",  enabled = true,  speed = 2.2, bezier = "easeOutCubic", style = "slidevert" })
hl.animation({ leaf = "workspacesOut", enabled = true,  speed = 2.2, bezier = "easeOutCubic", style = "slidevert" })
hl.animation({ leaf = "zoomFactor",    enabled = true,  speed = 7,    bezier = "quick" })

-- Ref https://wiki.hypr.land/Configuring/Basics/Workspace-Rules/
-- "Smart gaps" / "No gaps when only"
-- uncomment all if you wish to use that.
-- hl.workspace_rule({ workspace = "w[tv1]", gaps_out = 0, gaps_in = 0 })
-- hl.workspace_rule({ workspace = "f[1]",   gaps_out = 0, gaps_in = 0 })
-- hl.window_rule({
--     name  = "no-gaps-wtv1",
--     match = { float = false, workspace = "w[tv1]" },
--     border_size = 0,
--     rounding    = 0,
-- })
-- hl.window_rule({
--     name  = "no-gaps-f1",
--     match = { float = false, workspace = "f[1]" },
--     border_size = 0,
--     rounding    = 0,
-- })

-- See https://wiki.hypr.land/Configuring/Layouts/Dwindle-Layout/ for more
hl.config({
    dwindle = {
        preserve_split = true, -- You probably want this
        -- i3-like placement: a new window always opens to the right / below the
        -- focused one (instead of dwindle's default aspect-ratio/mouse guess).
        -- 0 = follow mouse, 1 = always left/top, 2 = always right/bottom.
        force_split = 2,
    },
})

-- See https://wiki.hypr.land/Configuring/Layouts/Master-Layout/ for more
hl.config({
    master = {
        new_status = "master",
    },
})

-- See https://wiki.hypr.land/Configuring/Layouts/Scrolling-Layout/ for more
hl.config({
    scrolling = {
        fullscreen_on_one_column = true,
    },
})

----------------
----  MISC  ----
----------------

hl.config({
    misc = {
	disable_splash_rendering = true, 
        force_default_wallpaper = 0,    -- Set to 0 or 1 to disable the anime mascot wallpapers
        disable_hyprland_logo   = true, -- If true disables the random hyprland logo / anime girl background. :(

        -- "Hyprland was started without start-hyprland. This is strongly
        -- discouraged unless you are in a debugging environment."
        -- That is deliberate here: the session's Exec is `hypr-supervise`
        -- (sys/dsk/hyprland.nix), which replaces start-hyprland's watchdog
        -- precisely because its answer to an unclean exit is --safe-mode.
        -- Ours restarts with the REAL config and quarantines the plugin build
        -- that died. We don't speak start-hyprland's --watchdog-fd protocol,
        -- so the compositor can't tell us apart from a raw `Hyprland` launch.
        disable_watchdog_warning = true,
    },
})


---------------
---- INPUT ----
---------------

hl.config({
    input = {
        kb_layout  = "us",
        kb_variant = "",
        kb_model   = "",
        kb_options = "",
        kb_rules   = "",

        -- 2: pointer focus follows hover (so scrolling scrolls the window
        -- UNDER the cursor) while keyboard focus still only moves on click.
        follow_mouse = 2,

        sensitivity = 0, -- -1.0 - 1.0, 0 means no modification. per-device override below.

        touchpad = {
            natural_scroll = false,
        },
    },
})

-- (3-finger workspace gesture removed: this desktop is locked to a single
-- workspace — the panel is a program taskbar, not a workspace switcher.)

-- Logitech ERGO M575 (trackball). Values carried over from the Plasma
-- install's kcminputrc ([Libinput][1133][16534][Logitech ERGO M575]):
-- PointerAcceleration=-0.200 -> sensitivity, PointerAccelerationProfile=1
-- -> "flat" (libinput's own enum: 0 none, 1 flat, 2 adaptive) — flat also
-- matches the usual trackball recommendation over adaptive accel.
-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Devices/ for more
hl.device({
    name          = "logitech-ergo-m575",
    sensitivity   = -0.200,
    accel_profile = "flat",
})

-- The SAME trackball over bluetooth, which is how book has it. Hyprland
-- matches a device rule on libinput's device name, lowercased with spaces
-- turned into dashes, and that name is per-transport: the USB receiver above
-- announces "Logitech ERGO M575" while bluetooth announces "ERGO M575 Mouse"
-- (`libinput list-devices`, bluetooth:046d:b027). So the rule above matched
-- nothing over bluetooth and the trackball silently ran on Hyprland's default
-- adaptive acceleration — the feel difference. A rule for an absent device is
-- inert, so both hosts carry both.
hl.device({
    name          = "ergo-m575-mouse",
    sensitivity   = -0.200,
    accel_profile = "flat",
})


---------------------
---- KEYBINDINGS ----
---------------------

local mainMod = "SUPER" -- Sets "Windows" key as main modifier

-- How far the pointer may travel before a press counts as a DRAG rather than a
-- click. Hyprland's default is 0, which means "no threshold" — and with no
-- threshold the Super-tap bind below (a `click` bind) would be cancelled by a
-- single pixel of mouse jitter. A few pixels is also the ordinary desktop
-- behaviour for picking a window up: the move starts once you have actually
-- moved, not on the press.
hl.config({
    binds = {
        drag_threshold = 6,
    },
})

-- Example binds, see https://wiki.hypr.land/Configuring/Basics/Binds/ for more
hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd(terminal), { description = "Open terminal" })
-- Close via the hyprvtb close path (roll-up + fade close animation, exactly as
-- if the titlebar [x] were clicked) instead of Hyprland's plain window.close.
local closeWindowBind = hl.bind(mainMod .. " + C", function()
    hl.plugin.hyprvtb.close_active()
end, { description = "Close window" })
-- closeWindowBind:set_enabled(false)
hl.bind(mainMod .. " + E", hl.dsp.exec_cmd(fileManager), { description = "File manager" })
hl.bind(mainMod .. " + V", hl.dsp.window.float({ action = "toggle" }), { description = "Toggle floating" })
hl.bind(mainMod .. " + F", hl.dsp.window.fullscreen(), { description = "Fullscreen" })
-- Drop the keybinding cheatsheet down from the top edge.
hl.bind(mainMod .. " + K", hl.dsp.exec_cmd("qs ipc call cheatsheet toggle"), { description = "Keybindings cheatsheet" })
-- Lock the session (slides in from the right; PAM-authenticated).
hl.bind(mainMod .. " + L", hl.dsp.exec_cmd("qs ipc call lock activate"), { description = "Lock screen" })
-- Power menu: logout/sleep/reboot/poweroff, slides out near the clock.
hl.bind(mainMod .. " + M", hl.dsp.exec_cmd("qs ipc call powermenu toggle"), { description = "Power menu" })
-- Wallpaper picker: flip through ~/Pictures/wall with arrow keys, each
-- highlight live-applies (wal-set.sh) as both wallpaper and theme.
hl.bind(mainMod .. " + W", hl.dsp.exec_cmd("qs ipc call wallpaper toggle"), { description = "Wallpaper picker" })
-- Hide/show the wallpaper image (the "no wallpaper" setting); the palette and
-- theme derived from it stay.
hl.bind(mainMod .. " + SHIFT + W", hl.dsp.exec_cmd("qs ipc call wallpaper toggleSolid"), { description = "Wallpaper on/off" })
-- Flip the desktop between light and dark from the same wallpaper hue; the
-- panel re-runs wal-set.sh and the whole desktop re-themes live (theme IPC).
hl.bind(mainMod .. " + D", hl.dsp.exec_cmd("qs ipc call theme toggle"), { description = "Toggle light/dark theme" })
-- Spectacle-style screenshot overlay (quickshell/Screenshot.qml): dim +
-- drag-select / window pick, delay + exit in the bottom menu; saves to
-- ~/Pictures/Screenshots and copies to the clipboard.
hl.bind(mainMod .. " + SHIFT + S", hl.dsp.exec_cmd("qs ipc call screenshot toggle"), { description = "Screenshot" })
-- Settings program: its own Quickshell instance (quickshell/Settings.qml),
-- toggled via the `settings` wrapper (it targets that instance by path, not the
-- panel's IPC). Meta+comma, the usual "preferences" chord. Absolute path — the
-- wrapper lives in the nix profile, which is NOT on Hyprland's exec PATH.
hl.bind(mainMod .. " + comma", hl.dsp.exec_cmd("$HOME/.nix-profile/bin/settings"), { description = "Settings" })
-- Bare Super tap opens the Quickshell runner (fires on release of Super).
--
-- `global`, not `exec_cmd`: hyprland-global-shortcuts-v1 hands the press
-- straight to the running panel (RunnerShortcut.qml claims `quickshell:launcher`),
-- where `qs ipc call launcher toggle` forked a shell and exec'd Quickshell's CLI
-- to say the same thing — 20-30ms of process, measured on book, on every tap.
-- The IPC path still exists and still works; it is just not on the key any more.
--
-- `click`, not plain `release`: it still fires at key-up (the flag implies
-- release), but ONLY if the pointer has not moved more than
-- `binds:drag_threshold` since Super went down. Holding Super to resize a
-- window with the right button used to pop the runner the moment Super came
-- back up — the resize is the plugin's, so Hyprland never saw a bind to shadow,
-- and a `global` handler is exempt from shadowing anyway
-- (`KeybindManager.cpp`'s shadowKeybinds: "can't be shadowed"). The pointer
-- having travelled across the screen is the signal that Super was a MODIFIER
-- and not a tap, and it costs the tap nothing: a hand on the keyboard moves the
-- mouse zero pixels.
hl.bind(mainMod .. " + Super_L", hl.dsp.global("quickshell:launcher"), { click = true })
hl.bind(mainMod .. " + P", hl.dsp.window.pseudo(), { description = "Pseudo-tile" })
hl.bind(mainMod .. " + J", hl.dsp.layout("togglesplit"), { description = "Toggle split" })    -- dwindle only

-- Move focus with mainMod + arrow keys
hl.bind(mainMod .. " + left",  hl.dsp.focus({ direction = "left" }),  { description = "Focus window" })
hl.bind(mainMod .. " + right", hl.dsp.focus({ direction = "right" }), { description = "Focus window" })
hl.bind(mainMod .. " + up",    hl.dsp.focus({ direction = "up" }),    { description = "Focus window" })
hl.bind(mainMod .. " + down",  hl.dsp.focus({ direction = "down" }),  { description = "Focus window" })

-- Move the focused window within the layout with mainMod + SHIFT + arrow keys
-- (same swap-toward-the-neighbor behaviour as mainMod + CTRL + arrow below).
hl.bind(mainMod .. " + SHIFT + left",  hl.dsp.window.move({ direction = "left" }),  { description = "Move window" })
hl.bind(mainMod .. " + SHIFT + right", hl.dsp.window.move({ direction = "right" }), { description = "Move window" })
hl.bind(mainMod .. " + SHIFT + up",    hl.dsp.window.move({ direction = "up" }),    { description = "Move window" })
hl.bind(mainMod .. " + SHIFT + down",  hl.dsp.window.move({ direction = "down" }),  { description = "Move window" })

-- Move the focused window within the layout with mainMod + CTRL + arrow keys
-- (i3-style: the window swaps toward the neighbor in the pressed direction).
hl.bind(mainMod .. " + CTRL + left",  hl.dsp.window.move({ direction = "left" }),  { description = "Move window" })
hl.bind(mainMod .. " + CTRL + right", hl.dsp.window.move({ direction = "right" }), { description = "Move window" })
hl.bind(mainMod .. " + CTRL + up",    hl.dsp.window.move({ direction = "up" }),    { description = "Move window" })
hl.bind(mainMod .. " + CTRL + down",  hl.dsp.window.move({ direction = "down" }),  { description = "Move window" })

-- meta + R rolls the active window's hyprvtb titlebar up/down (shade) — the
-- same toggle the titlebar's roll-up button issues (plugin's rollup lua fn).
hl.bind(mainMod .. " + R", function()
    hl.plugin.hyprvtb.rollup()
end, { description = "Roll window up/down" })

-- Workspace switching removed: this desktop is locked to ONE workspace.
-- Windows are managed through the panel taskbar (program icons) and the
-- hyprvtb titlebars (close / maximize / minimize-slide) instead.

-- Move windows with mainMod + LMB drag.
-- NO { mouse = true } here: that option makes Hyprland route the bind to the
-- "mouse" dispatcher with the lua closure's ref number as its argument
-- (KeybindManager.cpp:749) — the closure never runs and the bind is dead.
-- hl.dsp.window.drag() handles press/release itself (releasePending +
-- m_passPressed), so a plain bind is the correct form.
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag())
-- Resizing is NOT bound to a dispatcher at all: Hyprland's resizewindow (and
-- its native border resize) always resizes the two edges of the nearest
-- corner QUADRANT, even when you grab the middle of one side. The hyprvtb
-- plugin replaces both with KDE-style handles on floating windows:
--   * grab a border side  -> that edge only; grab a corner zone -> two edges
--   * the titlebar's outer strip is the right-edge handle
--   * mainMod + RMB drag  -> 3x3 zones over the window (KWin unrestricted
--     resize: outer ring = 8 handles, centre = nearest corner)

-- Scratchpad terminal (Meta+S): kitty sliding in from the left accent
-- edge, no titlebar, always at the bottom of the z-order; width is
-- drag-resizable on its right border and remembered. Logic lives in the
-- hyprvtb plugin.
hl.bind(mainMod .. " + S", function()
    hl.plugin.hyprvtb.toggle_scratch()
end, { description = "Scratchpad terminal" })

-- Save the current window session — every window's position, its
-- minimized/rolled/maximized state, and the command that launched it — to
-- ~/.local/state/hyprvtb/session.tsv. A fresh login relaunches and re-lays-out
-- everything. Manual on purpose (Meta+Ctrl+S); pops a confirmation
-- notification. Logic lives in the hyprvtb plugin.
--
-- The same keybind also snapshots the quickshell desktop widgets (which pins
-- are currently on the desktop — including any the user manually unpinned
-- after "show all"), so a fresh login restores them too. That state lives in
-- quickshell, not hyprvtb, so it's a separate qs IPC call rather than part of
-- the window session. See shell.qml's "widgets" IpcHandler / saveWidgets.
hl.bind(mainMod .. " + CTRL + S", function()
    hl.plugin.hyprvtb.save_session()
    hl.exec_cmd("qs ipc call widgets save")
end, { description = "Save window session + desktop widgets" })

-- Alt-Tab window switching, KDE-style most-recently-used order (hyprvtb
-- plugin). cycle_next walks the window LIST (creation order), which is why
-- tabbing felt out of order — cycle_hist walks focus history instead:
-- one alt-tab flips to the previous window; successive tabs within ~0.9s
-- keep digging into the same history snapshot (KDE's hold-Alt walk), and
-- pausing commits. Raise + minimized-restore ride on the plugin's focus
-- listener. Focusing a minimized window slides it back in.
hl.bind("ALT + TAB", function()
    hl.plugin.hyprvtb.cycle_hist_next()
end, { description = "Next window (recent first)" })
hl.bind("ALT + SHIFT + TAB", function()
    hl.plugin.hyprvtb.cycle_hist_prev()
end, { description = "Previous window" })

-- Multimedia keys for volume and brightness.
-- Volume: routed through quickshell's "volume" IpcHandler (optimistic
-- panel update + wpctl + the Vista ding). No OSD — the VU meter's level
-- line in the bar is the always-visible indicator.
-- Brightness: this display is external (DDC/CI via ddcutil, no laptop
-- backlight), and ddcutil takes ~1.5s/call — routed through Quickshell's
-- SysInfo.adjustBrightness (debounced write + its own OSD trigger) instead
-- of calling ddcutil directly, so holding the key doesn't stack up several
-- slow DDC calls. See quickshell/shell.qml's "brightness" IpcHandler.
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("qs ipc call volume up"),                          { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("qs ipc call volume down"),                        { locked = true, repeating = true })
hl.bind("XF86AudioMute",        hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),     { locked = true, repeating = true })
hl.bind("XF86AudioMicMute",     hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"),   { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp",  hl.dsp.exec_cmd("qs ipc call brightness up"),                       { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown",hl.dsp.exec_cmd("qs ipc call brightness down"),                     { locked = true, repeating = true })

-- Requires playerctl
hl.bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"),       { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"),   { locked = true })

-- Lid switch — laptops only (host.laptop, i.e. air/book; top is a desktop and
-- has no lid device to bind to). WHAT it does is a user setting, `lidClose` in
-- ~/.config/quickshell/settings.json (suspend | lock | blank | nothing) — the
-- script re-reads it on every event, so changing it applies at once. logind is
-- kept out of the lid by the lid-inhibit user service; the whole mechanism is
-- documented in home/srvs/lid.nix.
--
-- `locked = true` is not optional here: without it the bind is dead exactly
-- when it matters most, on a lid closed over a locked session.
if host.laptop then
    hl.bind("switch:on:Apple SMC power/lid events",
            hl.dsp.exec_cmd("$HOME/.config/scripts/lid-close.sh close"),
            { locked = true, description = "Lid closed" })
    hl.bind("switch:off:Apple SMC power/lid events",
            hl.dsp.exec_cmd("$HOME/.config/scripts/lid-close.sh open"),
            { locked = true, description = "Lid opened" })
end


--------------------------------
---- WINDOWS AND WORKSPACES ----
--------------------------------

-- See https://wiki.hypr.land/Configuring/Basics/Window-Rules/
-- and https://wiki.hypr.land/Configuring/Basics/Workspace-Rules/

-- Example window rules that are useful

local suppressMaximizeRule = hl.window_rule({
    -- Ignore maximize requests from all apps. You'll probably like this.
    name  = "suppress-maximize-events",
    match = { class = ".*" },

    suppress_event = "maximize",
})
-- suppressMaximizeRule:set_enabled(false)

-- Every window floats by default. dwindle/master layout config below is left
-- in place, unused while this rule is enabled — mainMod+V (window.float
-- toggle) still drops an individual window back into tiling if you want it.
hl.window_rule({
    name  = "float-by-default",
    match = { class = ".*" },
    float = true,
})

hl.window_rule({
    -- Fix some dragging issues with XWayland
    name  = "fix-xwayland-drags",
    match = {
        class      = "^$",
        title      = "^$",
        xwayland   = true,
        float      = true,
        fullscreen = false,
        pin        = false,
    },

    no_focus = true,
})

hl.window_rule({
    -- Vista-UAC treatment for the sudo password dialog (apps/askpass, spawned
    -- by the sudo-askpass wrapper in ~/nix/home/prog/askpass.nix): dim
    -- everything around it, centre it, pin it above the stack. The wrapper
    -- plays the UAC chime alongside.
    --
    -- dim_around only covers the WINDOW pass, so the Quickshell bar (a
    -- layer-shell surface on the `top` layer) stays bright — the panel dims
    -- itself in lock-step, keyed off this same app-id, in Askpass.qml. The
    -- app-id `vista-askpass` is therefore load-bearing in three places: here,
    -- Askpass.qml, and apps/askpass/main.py.
    --
    -- The old ksshaskpass class (^org\.kde\.ksshaskpass$) is kept as a second
    -- alternative so the fallback path in askpass.nix — which fires if the Qt
    -- dialog cannot start — still gets the same treatment.
    name  = "askpass-dim",
    match = { class = "^(vista-askpass|org\\.kde\\.ksshaskpass)$" },

    dim_around = true,
    center     = true,
    pin        = true,
})

-- Layer rules also return a handle.
-- local overlayLayerRule = hl.layer_rule({
--     name  = "no-anim-overlay",
--     match = { namespace = "^my-overlay$" },
--     no_anim = true,
-- })
-- overlayLayerRule:set_enabled(false)

-- THE RUNNER DRAWER MUST NOT FADE IN OR OUT (`qs-launcher`, Launcher.qml).
-- It is the shortcut notch pulled out of the panel: closed it is drawn pixel
-- for pixel on top of the notch, so mapping and unmapping the surface is meant
-- to be invisible and the ONLY thing that may be seen is its travel. But
-- `layersIn`/`layersOut` are enabled (style = "fade"), so every open faded the
-- drawer up over the notch and every close faded it out — [his] "i can still
-- see the transistion between the unrolled and rolled bar". Nothing else on
-- this desktop wants that exemption; keep it to this namespace.
hl.layer_rule({
    name    = "no-anim-runner-drawer",
    match   = { namespace = "^qs-launcher$" },
    no_anim = true,
})

-- Hyprland-run windowrule
hl.window_rule({
    name  = "move-hyprland-run",
    match = { class = "hyprland-run" },

    move  = "20 monitor_h-120",
    float = true,
})

-- AN AGENT'S TEST WINDOW MAY NEVER HOLD THIS SEAT.
--
-- `tools/sandbox.sh` launches every window it starts with `tag +sandbox`, onto
-- a headless output nobody can see. That hid the window but NOT the keyboard:
-- measured on top 2026-07-30 on the event socket, every launch was an
-- `openwindow>>` followed immediately by `activewindow>>` naming the test
-- window, and the next two seconds of typing went to a monitor with no cable
-- in it. A single harness run launches dozens of those.
--
-- `no_focus` is what actually holds, and it was the third thing tried.
-- `no_initial_focus` was measured NOT to work here — the sandbox workspace is
-- the ACTIVE workspace of its own monitor, so a map onto it is an ordinary
-- focus rather than the initial-focus-onto-a-hidden-workspace that rule
-- governs — and the `silent` in the exec rule only ever stopped the VIEW from
-- switching. `no_focus` also closes the pointer route ("Ignoring focus to
-- nofocus window!") and with it the clipboard, since a client needs a focus
-- serial before it may own the selection.
--
-- The cost is intended: a sandbox window cannot be typed into AT ALL. A
-- harness that must send input to the thing it is testing wants a nested
-- compositor with its own seat (home/prog/hyprvtb/tools/*.sh), not this
-- monitor.
--
-- Valid `match` keys, measured against this build rather than guessed (an
-- unknown one is refused by name in `hyprctl configerrors`): class, title,
-- initial_class, initial_title, tag, workspace, xwayland, float, fullscreen,
-- pin, focus. NOT monitor, onworkspace, floating, pinned, content_type.
hl.window_rule({
    name  = "sandbox-never-takes-the-seat",
    match = { tag = "sandbox" },

    no_focus = true,
})
