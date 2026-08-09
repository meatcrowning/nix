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

  # Build CUDA kernels for the ONE GPU that runs them, not for nine.
  #
  # nixpkgs' default `cudaCapabilities` is a fat-binary list — 7.5, 8.0, 8.6,
  # 8.9, 9.0, 10.0, 10.3, 12.0, 12.1 — and packages bake it straight into their
  # build; ollama-cuda emits a literal
  # `-DCMAKE_CUDA_ARCHITECTURES='75;80;86;89;90;100;103;120;121'`. Device code
  # is generated once per architecture, so a from-source CUDA build here paid
  # ~9x for eight architectures this card cannot execute: measured 2026-08-09,
  # 185 ggml-cuda kernels at 5.3/min, ~35 minutes, on a box that was neither
  # thermally throttled (57°C) nor memory-capped nor I/O-bound — just doing
  # nine times the work.
  #
  # That is not only a slow build. ollama-cuda is not in any substituter at
  # this pin, so it compiles locally, and at that width it is heavy enough to
  # livelock the machine when anything else wants the 30 GiB — which it did
  # twice on 2026-08-09, both times against a ComfyUI render (the incident
  # sys/nix-build-limits.nix and sys/oomd.nix were written for). Narrowing this
  # shrinks the collision itself, not just the wait.
  #
  # 12.0 is `top`'s RTX 5070, measured, not assumed:
  #   nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader
  # REVISIT IF THE CARD CHANGES — a list that omits the installed GPU's
  # capability means no kernels for it, and the failure is at runtime.
  #
  # `cudaForwardCompat` is left at nixpkgs' default (true), so PTX for sm_120
  # is still emitted and a newer card can JIT rather than find nothing.
  #
  # This lives here rather than in flake.nix's `mkPkgs`: `nixosConfigurations.top`
  # is built by `nixpkgs.lib.nixosSystem` and never calls that function (only
  # `pkgsAir` does), so a config set there does not reach this host at all.
  nixpkgs.config.cudaCapabilities = [ "12.0" ];

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
