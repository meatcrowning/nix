hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })
hl.config({
    general = { gaps_in = 3, gaps_out = 5, border_size = 1, layout = "dwindle", resize_on_border = true },
    decoration = { rounding = 0, blur = { enabled = false }, shadow = { enabled = false } },
    animations = { enabled = false },
    input = { kb_layout = "us", touchpad = { tap_to_click = true, natural_scroll = true } },
    misc = { disable_hyprland_logo = true, disable_splash_rendering = true },
})
hl.on("hyprland.start", function()
    hl.exec_cmd("uwsm finalize HYPRLAND_INSTANCE_SIGNATURE")
    for _, command in ipairs({
        "waybar", "mako", "lxqt-policykit-agent",
        "swayidle -w timeout 300 'swaylock -f -c 202020' timeout 1200 'systemctl suspend' before-sleep 'swaylock -f -c 202020'",
    }) do hl.exec_cmd(command) end
end)
local function run(key, command)
    hl.bind(key, hl.dsp.exec_cmd(command))
end
run("SUPER + Return", "foot")
run("SUPER + D", "fuzzel")
run("SUPER + B", "vivaldi")
run("SUPER + E", "thunar")
run("SUPER + N", "mousepad")
run("SUPER + L", "swaylock -f -c 202020")
run("SUPER + W", "foot nmtui")
run("SUPER + SHIFT + E", "uwsm stop")
run("Print", "grim -g \"$(slurp)\" - | wl-copy")
hl.bind("SUPER + Q", hl.dsp.window.close())
hl.bind("SUPER + F", hl.dsp.window.fullscreen())
hl.bind("SUPER + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind("SUPER + mouse:272", hl.dsp.window.drag())
hl.bind("SUPER + mouse:273", hl.dsp.window.resize())
for i = 1, 5 do
    hl.bind("SUPER + " .. i, hl.dsp.focus({ workspace = i }))
    hl.bind("SUPER + SHIFT + " .. i, hl.dsp.window.move({ workspace = i }))
end
for _, direction in ipairs({ "left", "right", "up", "down" }) do
    hl.bind("SUPER + " .. direction, hl.dsp.focus({ direction = direction }))
    hl.bind("SUPER + SHIFT + " .. direction, hl.dsp.window.move({ direction = direction }))
end
for key, command in pairs({
    XF86AudioRaiseVolume = "wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+",
    XF86AudioLowerVolume = "wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-",
    XF86AudioMute = "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle",
    XF86AudioMicMute = "wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle",
    XF86MonBrightnessUp = "brightnessctl set +5%",
    XF86MonBrightnessDown = "brightnessctl -n 1 set 5%-",
}) do hl.bind(key, hl.dsp.exec_cmd(command), { locked = true, repeating = true }) end
