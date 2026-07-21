{ host, ... }:

{
  # Read-only, regenerated every switch (unlike hyprland.lua, which is
  # seeded once and then left alone) — hyprland.lua's monitor block
  # `dofile`s this to pick up the per-host scale without needing its own
  # per-host branch baked into the seeded-once template.
  xdg.configFile."hypr/host.lua".text = ''
    return {
      scale = "${if host == "air" then "1.67" else "1"}",
      laptop = ${if host == "air" then "true" else "false"},
    }
  '';
}
