{ config, pkgs, lib, ... }:

let
  pkgId = "org.kde.lam.playervisualizer";
  cavaConfig = pkgs.writeText "player-visualizer-cava.conf"
    (builtins.readFile ./plasma-player-visualizer-files/cava.conf);
  state = pkgs.writeShellApplication {
    name = "plasma-player-visualizer-state";
    runtimeInputs = [ pkgs.cava pkgs.python3 ];
    text = ''
      export CAVA=${pkgs.cava}/bin/cava
      export PLAYER_VISUALIZER_CAVA_CONFIG=${cavaConfig}
      exec ${pkgs.python3}/bin/python3 ${./plasma-player-visualizer-files/cava-state.py}
    '';
  };
  metadata = builtins.toJSON {
    KPackageStructure = "Plasma/Applet";
    KPlugin = {
      Id = pkgId;
      Name = "Player Visualizer";
      Description = "Cava fallback beside the media controller";
      Category = "Multimedia";
      Icon = "view-media-visualization";
      EnabledByDefault = true;
      Version = "1.0";
    };
    "X-Plasma-API-Minimum-Version" = "6.0";
  };
  package = pkgs.runCommand pkgId { } ''
    mkdir -p $out/contents/ui
    cp ${pkgs.writeText "metadata.json" metadata} $out/metadata.json
    cp ${./plasma-player-visualizer-files/main.qml} $out/contents/ui/main.qml
  '';
in {
  # KWin resolves the patched decoration from the top system profile.  It must
  # not also enter the user profile: player already brings in stock Oxygen,
  # and buildEnv correctly rejects two providers for the same plugin path.
  xdg.dataFile."plasma/plasmoids/${pkgId}".source = package;
  systemd.user.services.plasma-player-visualizer = {
    Unit = { Description = "Cava state for the Plasma player visualizer"; After = [ "graphical-session.target" ]; };
    Service = { ExecStart = "${state}/bin/plasma-player-visualizer-state"; Restart = "on-failure"; RestartSec = 2; };
    Install.WantedBy = [ "graphical-session.target" ];
  };
  systemd.user.services.plasma-player-visualizer-install = {
    Unit = { Description = "Place player visualizer beside Plasma media"; After = [ "graphical-session.target" ]; };
    Service = {
      Type = "oneshot";
      Environment = [ "PATH=${lib.makeBinPath [ pkgs.coreutils ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/usr/bin:/bin" ];
      ExecStart = pkgs.writeShellScript "plasma-player-visualizer-install" ''
        for attempt in $(seq 1 60); do
          if qdbus org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript ${lib.escapeShellArg ''
            var target = null;
            var present = false;
            for (var i = 0; i < panelIds.length; ++i) {
              var panel = panelById(panelIds[i]);
              var widgets = panel.widgets();
              for (var j = 0; j < widgets.length; ++j) {
                if (widgets[j].type === "org.kde.plasma.mediacontroller") target = panel;
                if (widgets[j].type === "${pkgId}") present = true;
              }
            }
            if (!present && target) target.addWidget("${pkgId}");
          ''} >/dev/null 2>&1; then exit 0; fi
          sleep 1
        done
        exit 1
      '';
    };
    Install.WantedBy = [ "graphical-session.target" ];
  };
}
