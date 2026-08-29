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

  # book only: the gate above handles the startup race, but the chain breaks
  # again on idle. EasyEffects links easyeffects_sink:monitor ->
  # audio_effect.j313-convolver when it starts; that link (and its ports) is
  # torn down ~5-25s after the last stream goes quiet, and a NEW stream does not
  # bring it back — measured on book 2026-08-29: restart, link present and
  # surviving active playback, gone ~25s after idle, and a fresh pw-play into
  # easyeffects_sink does not re-create it. Apps keep playing into
  # easyeffects_sink, so they are silent while the default-sink path (system
  # chirp) still works. Neither WirePlumber config prevents it (EasyEffects owns
  # the link and the ports are not externally linkable), so a restart of
  # easyeffects is the only reliable heal. A daemon watches `pactl subscribe`
  # and restarts easyeffects the moment an app is playing into easyeffects_sink
  # while the onward link is missing — event-driven, so the heal lands in ~1s
  # rather than on a poll tick (a poll-only version left up to 15s of silence
  # at the start of each playback after idle). It never acts on idle, where no
  # link is the normal state. When it fires, audio is ALREADY silent, so the
  # restart restores sound rather than cutting it. See
  # easyeffects-files/easyeffects-link-watch.py.
  xdg.configFile."scripts/easyeffects-link-watch.py" = {
    source = ./easyeffects-files/easyeffects-link-watch.py;
    executable = true;
  };
  systemd.user.services.easyeffects-link-watch = {
    Unit = {
      Description = "Restart easyeffects if its sink loses the convolver link while audio plays";
      # Persistent daemon: restarts on failure, but never auto-restarts in a
      # tight loop (the script is idempotent and only acts when both a playing
      # stream and a missing link hold).
      StartLimitIntervalSec = 0;
    };
    Service = {
      Type = "simple";
      # pactl on book is Fedora's /usr/bin/pactl — nixpkgs' libpulseaudio ships
      # no pactl binary at all, so the tail is load-bearing (see the board-watch
      # PATH comment for the full per-host layout rationale). systemctl comes
      # from the same Fedora tail.
      Environment = [ "PATH=${lib.makeBinPath [ pkgs.coreutils pkgs.pipewire ]}:/usr/bin:/bin" ];
      ExecStart = "${pkgs.python3}/bin/python3 %h/.config/scripts/easyeffects-link-watch.py";
      Restart = "on-failure";
      RestartSec = 5;
    };
    Install.WantedBy = [ "default.target" ];
  };
}
