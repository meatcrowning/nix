{ config, pkgs, ... }:

{
  hardware = {
    graphics = { enable = true; enable32Bit = true; };
    nvidia = {
      modesetting.enable = true;
      open = true;
      nvidiaSettings = true;
      powerManagement.enable = false;
    };
  };

  boot.kernelParams = [
    "nvidia-drm.modeset=1"
    "nvidia-drm.fbdev=1"
    "nvidia.NVreg_OpenRmEnableUnsupportedGpus=1"
  ];

  services.xserver.videoDrivers = [ "nvidia" ];

  # NVIDIA's hardware cursor plane leaves a static/ghost cursor on Wayland
  # compositors (Hyprland confirmed on this RTX 5070). Hyprland's own
  # cursor:no_hardware_cursors config option alone wasn't enough to fix it —
  # this is the more fundamental fix (affects the DRM backend directly,
  # including XWayland clients), but has to be set before the compositor
  # starts, so it goes here rather than in hyprland.lua. Requires a fresh
  # login (not just a config reload) to take effect.
  environment.sessionVariables = {
    WLR_NO_HARDWARE_CURSORS = "1";
  };
}
