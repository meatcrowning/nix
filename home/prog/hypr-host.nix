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
      -- Force Hyprland's software cursor only where the hardware cursor plane
      -- misbehaves: on `top` (NVIDIA RTX 5070) it leaves a static ghost cursor.
      -- Elsewhere (air = Apple/Asahi GPU) use the hardware cursor — its plane
      -- updates immediately on `hyprctl setcursor`, so the wal accent re-tint
      -- shows at once instead of only after you hover something (the software
      -- cursor never re-rasterises the on-screen shape on a live theme change).
      no_hardware_cursors = ${if host == "air" then "false" else "true"},
    }
  '';
}
