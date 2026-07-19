{ config, pkgs, lib, ... }:

{
  services = {
    # Swapped SDDM for ly: SDDM's greeter is itself Wayland/DRM-capable and
    # on this NVIDIA card sometimes fails to reacquire the DRM master after
    # a Wayland compositor session ends (plausible cause of the Hyprland
    # logout hang — `hyprctl dispatch exit` kills the compositor fine, but
    # nothing visible ever happens afterward). ly is a plain TTY/framebuffer
    # greeter — it never competes for DRM/Wayland resources, so this class
    # of handoff bug shouldn't apply to it at all. Still launches Plasma the
    # same way (session .desktop files are DM-agnostic).
    displayManager.sddm.enable = false;
    displayManager.ly.enable = true;
    # The "wavy" colormix shader animation, themed to the desktop's wal
    # palette. NOTE: this is a static snapshot of the palette (orange, as of
    # 2026-07) — ly's config is system-level and can't follow wallpaper
    # changes. Colors are 0xSSRRGGBB (SS = styling; 01 = bold).
    displayManager.ly.settings = {
      animation = "colormix";
      colormix_col1 = "0x00CC4400"; # accent
      colormix_col2 = "0x0054382A"; # dim
      colormix_col3 = "0x20000000"; # near-black (hi-black style)
      fg = "0x00E08E65";            # input text — palette "ok", readable on the waves
      border_fg = "0x00CC4400";     # box border = accent
      error_fg = "0x01FA5C0C";      # bold crit
    };
    desktopManager.plasma6.enable = true;
    # Hyprland is the default session; aerotheme (when enabled) takes over instead.
    # Plasma stays installed and selectable at the greeter — it also supplies
    # dolphin on PATH and xdg-desktop-portal-kde, which the Hyprland setup uses.
    displayManager.defaultSession =
      if config.my.aerotheme.enable then "aerothemeplasma" else "hyprland";
  };

  programs.aeroshell = lib.mkIf config.my.aerotheme.enable {
    enable = true;
    fonts.segoe.enable = true;
    fonts.lucida.enable = false;
    polkit.enable = true;
    aerothemeplasma = {
      enable = true;
      sddm.enable = true;
      plymouth.enable = false;
    };
  };
}
