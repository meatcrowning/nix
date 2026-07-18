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
    desktopManager.plasma6.enable = true;
    displayManager.defaultSession = lib.mkIf config.my.aerotheme.enable (lib.mkForce "aerothemeplasma");
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
