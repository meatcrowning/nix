-- Refer to the wiki for more information.
-- https://wiki.hypr.land/Configuring/Start/

------------------
---- MONITORS ----
------------------

-- See https://wiki.hypr.land/Configuring/Basics/Monitors/
hl.monitor({
    output   = "",
    mode     = "preferred",
    position = "auto",
    scale    = "1",
})

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
--   hl.exec_cmd("waybar & hyprpaper & firefox")
-- end)

-- Quickshell vertical panel (bar + launcher + workspaces + tray + clock)
hl.on("hyprland.start", function()
    -- QS_NO_RELOAD_POPUP suppresses Quickshell's built-in top-left reload popup;
    -- we surface reloads as our own native toasts instead (see shell.qml). The
    -- flag is read-only from QML, so it has to be set in the environment here.
    hl.exec_cmd("QS_NO_RELOAD_POPUP=1 qs -d")
    -- Idle daemon: locks after 5 min / before sleep, blanks the screen.
    -- See ~/.config/hypr/hypridle.conf.
    hl.exec_cmd("hypridle")
    -- Polkit authentication agent. Plasma autostarts this itself; Hyprland
    -- doesn't, so without it any polkit-gated action (loginctl
    -- terminate-session for the power menu's logout, NetworkManager admin
    -- actions, udisks mounts, etc.) hangs forever waiting on an
    -- authorization prompt nothing is running to show.
    hl.exec_cmd("polkit-kde-agent-1")
    -- Tile the current wallpaper via hyprpaper and recolour the panel,
    -- kitty and this border from it. See ~/.config/scripts/wal-set.sh.
    hl.exec_cmd("$HOME/.config/scripts/wal-set.sh")
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
    -- Same for wal-prepare.path, which pre-caches tile/theme data for every
    -- image under ~/Pictures/wall as soon as it's added — see
    -- scripts/wal-prepare.sh — so WallpaperPicker.qml flips land fast. Also
    -- backfill anything already in that directory from before this existed.
    hl.exec_cmd("systemctl --user start wal-prepare.path")
    hl.exec_cmd("$HOME/.config/scripts/wal-prepare-all.sh")
    -- Land on the "main" workspace (50, not 1) so a scroll-to-create
    -- workspace scheme has numeric room to grow both up (49, 48, ...) and
    -- down (51, 52, ...) from a central anchor, instead of hitting the floor
    -- immediately at workspace 1. (The original WorkspaceNav.qml consumer of
    -- this was removed with the Taskbar rework; the anchor is kept as-is.)
    hl.exec_cmd([[hyprctl dispatch 'hl.dsp.focus({ workspace = 50 })']])
end)

-- Compositor-drawn vertical titlebars (close / maximize / rotated title,
-- right edge of every window): the hyprvtb plugin — C++ source in
-- ~/nix/home/prog/hyprvtb/, built by nix and symlinked to a stable path by
-- home-manager. A window decoration renders in the same frame as its window
-- (locked), which no layer-shell client could do; this replaced the old
-- quickshell titlebars and the in-compositor geometry event stream that
-- fed them.
hl.plugin.load("/home/lam/.config/hypr/plugins/libhyprvtb.so")
hl.config({
    plugin = {
        hyprvtb = {
            -- colour lines rewritten by wal-set.sh alongside active_border
            ["col.text"]          = "rgba(8c7138ff)",
            ["col.button_border"] = "rgba(382d16ff)",
            ["col.accent"]        = "rgba(d99c1fff)",
            ["col.bg_alt"]        = "rgba(120f08ff)",
            ["col.crit"]          = "rgba(fab424ff)",
        },
    },
})


-------------------------------
---- ENVIRONMENT VARIABLES ----
-------------------------------

-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Environment-variables/

hl.env("XCURSOR_SIZE", "22")
hl.env("HYPRCURSOR_SIZE", "22")
-- Same cursor theme as the Plasma install (~/.icons/GoogleDot-Black,
-- kcminputrc's cursorTheme). hyprcursor falls back to loading it as a plain
-- XCursor theme since it's not a native .hyprcursor theme.
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
        -- NVIDIA's hardware cursor plane leaves a static ghost cursor behind
        -- on this GPU (RTX 5070) — force the software cursor unconditionally
        -- instead of relying on Hyprland's auto-detection.
        no_hardware_cursors = true,
    },
    general = {
        gaps_in  = 5,
        gaps_out = 35,

        border_size = 2,

        col = {
	    active_border = "rgba(5c9fccee)",
            -- active_border   = { colors = {"rgba(33ccffee)", "rgba(00ff99ee)"}, angle = 45 },
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

        shadow = {
            enabled      = true,
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


---------------------
---- KEYBINDINGS ----
---------------------

local mainMod = "SUPER" -- Sets "Windows" key as main modifier

-- Example binds, see https://wiki.hypr.land/Configuring/Basics/Binds/ for more
hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd(terminal), { description = "Open terminal" })
local closeWindowBind = hl.bind(mainMod .. " + C", hl.dsp.window.close(), { description = "Close window" })
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
-- Bare Super tap opens the Quickshell runner (fires on release of Super).
hl.bind(mainMod .. " + Super_L", hl.dsp.exec_cmd("qs ipc call launcher toggle"), { release = true })
hl.bind(mainMod .. " + P", hl.dsp.window.pseudo(), { description = "Pseudo-tile" })
hl.bind(mainMod .. " + J", hl.dsp.layout("togglesplit"), { description = "Toggle split" })    -- dwindle only

-- Move focus with mainMod + arrow keys
hl.bind(mainMod .. " + left",  hl.dsp.focus({ direction = "left" }),  { description = "Focus window" })
hl.bind(mainMod .. " + right", hl.dsp.focus({ direction = "right" }), { description = "Focus window" })
hl.bind(mainMod .. " + up",    hl.dsp.focus({ direction = "up" }),    { description = "Focus window" })
hl.bind(mainMod .. " + down",  hl.dsp.focus({ direction = "down" }),  { description = "Focus window" })

-- Move the focused window within the layout with mainMod + SHIFT + arrow keys
-- (same swap-toward-the-neighbor behaviour as mainMod + CTRL + arrow below;
-- resizing now lives in the dedicated resize mode — see mainMod + R).
local resizeStep = 40
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

-- i3-style resize mode: mainMod + R enters it, mainMod + R again exits it.
-- These binds only take effect while the "resize" submap is active, so bare
-- arrow keys are left alone (passed through to apps) the rest of the time.
-- While active: bare arrow keys resize the focused window, mainMod + arrow
-- keys move it instead of the usual focus-cycling. A notify-send toast (the
-- same path every other toast in this config uses, see scripts/resize-mode-
-- notify.sh) confirms the mode, driven off the keybinds.submap event below.
hl.define_submap("resize", function()
    hl.bind("left",  hl.dsp.window.resize({ x = -resizeStep, y = 0,           relative = true }), { repeating = true, description = "Resize window" })
    hl.bind("right", hl.dsp.window.resize({ x =  resizeStep, y = 0,           relative = true }), { repeating = true, description = "Resize window" })
    hl.bind("up",    hl.dsp.window.resize({ x = 0,           y = -resizeStep, relative = true }), { repeating = true, description = "Resize window" })
    hl.bind("down",  hl.dsp.window.resize({ x = 0,           y =  resizeStep, relative = true }), { repeating = true, description = "Resize window" })

    hl.bind(mainMod .. " + left",  hl.dsp.window.move({ direction = "left" }),  { description = "Move window" })
    hl.bind(mainMod .. " + right", hl.dsp.window.move({ direction = "right" }), { description = "Move window" })
    hl.bind(mainMod .. " + up",    hl.dsp.window.move({ direction = "up" }),    { description = "Move window" })
    hl.bind(mainMod .. " + down",  hl.dsp.window.move({ direction = "down" }),  { description = "Move window" })

    hl.bind(mainMod .. " + R", hl.dsp.submap("reset"), { description = "Exit resize mode" })
end)

hl.bind(mainMod .. " + R", hl.dsp.submap("resize"), { description = "Enter resize mode" })

hl.on("keybinds.submap", function(name)
    hl.exec_cmd("$HOME/.config/scripts/resize-mode-notify.sh " .. (name == "resize" and "enter" or "leave"))
end)

-- Workspace switching removed: this desktop is locked to ONE workspace.
-- Windows are managed through the panel taskbar (program icons) and the
-- hyprvtb titlebars (close / maximize / minimize-slide) instead.

-- Move windows with mainMod + LMB drag.
-- Resizing is deliberately NOT bound to mainMod + RMB: that dispatcher
-- (resizewindow) always resizes the TWO edges of whichever corner is nearest
-- the cursor, so a drag that feels like "one side" moves two at once. Resize
-- instead by grabbing the window border directly (general:resize_on_border,
-- enabled above) — that path is edge-aware: grab a side to move just that
-- edge, grab a corner to move the two edges meeting there.
-- extend_border_grab_area (15px) widens the catch zone for the thin 2px border.
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })

-- Scratchpad terminal (Meta+S): kitty sliding in from the left accent
-- edge, no titlebar, always at the bottom of the z-order; width is
-- drag-resizable on its right border and remembered. Logic lives in the
-- hyprvtb plugin.
hl.bind(mainMod .. " + S", function()
    hl.plugin.hyprvtb.toggle_scratch()
end, { description = "Scratchpad terminal" })

-- Alt-Tab window switching (single-workspace desktop): cycle focus and
-- raise. Focusing a minimized window slides it back in (hyprvtb).
hl.bind("ALT + TAB", function()
    hl.dispatch(hl.dsp.window.cycle_next())
    hl.dispatch(hl.dsp.window.bring_to_top())
end, { description = "Next window" })
hl.bind("ALT + SHIFT + TAB", function()
    hl.dispatch(hl.dsp.window.cycle_next({ prev = true }))
    hl.dispatch(hl.dsp.window.bring_to_top())
end, { description = "Previous window" })

-- Multimedia keys for volume and brightness.
-- Volume: each also pops the Quickshell OSD (`qs ipc call osd volume`),
-- which re-reads the live level and shows it briefly.
-- Brightness: this display is external (DDC/CI via ddcutil, no laptop
-- backlight), and ddcutil takes ~1.5s/call — routed through Quickshell's
-- SysInfo.adjustBrightness (debounced write + its own OSD trigger) instead
-- of calling ddcutil directly, so holding the key doesn't stack up several
-- slow DDC calls. See quickshell/shell.qml's "brightness" IpcHandler.
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+ && qs ipc call osd volume"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%- && qs ipc call osd volume"),      { locked = true, repeating = true })
hl.bind("XF86AudioMute",        hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle && qs ipc call osd volume"),     { locked = true, repeating = true })
hl.bind("XF86AudioMicMute",     hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"),   { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp",  hl.dsp.exec_cmd("qs ipc call brightness up"),                       { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown",hl.dsp.exec_cmd("qs ipc call brightness down"),                     { locked = true, repeating = true })

-- Requires playerctl
hl.bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"),       { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"),   { locked = true })


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

-- Layer rules also return a handle.
-- local overlayLayerRule = hl.layer_rule({
--     name  = "no-anim-overlay",
--     match = { namespace = "^my-overlay$" },
--     no_anim = true,
-- })
-- overlayLayerRule:set_enabled(false)

-- Hyprland-run windowrule
hl.window_rule({
    name  = "move-hyprland-run",
    match = { class = "hyprland-run" },

    move  = "20 monitor_h-120",
    float = true,
})
