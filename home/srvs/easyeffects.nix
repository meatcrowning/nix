{ config, pkgs, lib, host, ... }:

{
  # EasyEffects is stock again as of 8.2.8: the per-channel local-server IPC
  # (wwmm/easyeffects 76a3f9a5) the panel EQ needs is upstream now, so the
  # flake.nix overlay that used to backport it is gone. That socket call —
  #
  #   set_property:output:equalizer:0:left:band2Gain:-3.0
  #
  # — is what the panel probes for before enabling live-edit; a nixpkgs
  # downgrade below 8.2.8 makes the panel EQ read-only again.
  services.easyeffects.enable = true;

  # book only: the window ABORTS without this. EasyEffects 8's UI is QtQuick,
  # and a nix-built Qt app on Fedora Asahi loads nix's libglvnd libEGL, which
  # has no vendor ICD to load — "EGL not available", then "Failed to create
  # RHI (backend 2)" and SIGABRT the moment a window is asked for. The service
  # survives (audio keeps working), so the symptom is "easyeffects won't open"
  # with the daemon plainly running. The panel escapes this only because book
  # runs Fedora's quickshell rpm, which gets /usr/lib64/libEGL. Until host-Mesa
  # injection exists here (see home/pkgs/desktop/wm.nix), render the UI in
  # software — it is a settings window, not a game.
  systemd.user.services.easyeffects.Service.Environment =
    lib.mkIf (host == "air") [ "QT_QUICK_BACKEND=software" ];
}
