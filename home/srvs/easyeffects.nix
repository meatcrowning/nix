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

  # book only: easyeffects starts on graphical-session.target with no After= on
  # pipewire/wireplumber, so at login it can race ahead of asahi-audio's
  # convolver filter-chain (audio_effect.j313-convolver). If it starts first it
  # logs "Could not find a node related to alsa_card.platform-audio.1.auto" and
  # never creates its sink->convolver link, so program audio (which routes
  # through easyeffects_sink) is silent while the default-sink path (system
  # chirp, straight into the convolver) still works. Wait for the node before
  # starting so easyeffects creates its links on the first try instead of
  # needing a restart.
  systemd.user.services.easyeffects.Service.ExecStartPre =
    lib.mkIf (host == "air") [
      (lib.concatStringsSep " " [
        "${pkgs.bash}/bin/bash" "-c"
        (lib.escapeShellArg
          "for i in $(seq 1 30); do ${pkgs.pipewire}/bin/pw-cli list-objects Node 2>/dev/null | ${pkgs.gnugrep}/bin/grep -q audio_effect.j313-convolver && exit 0; ${pkgs.coreutils}/bin/sleep 1; done; echo 'convolver node not found after 30s' >&2; exit 1")
      ])
    ];
}
