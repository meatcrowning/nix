{ pkgs, user, ... }:
let
  python = pkgs.python3.withPackages (ps: [ ps.aiohttp ps.dbus-next ]);
  bridge = pkgs.writeShellScript "steam-system-colors" ''
    exec ${python}/bin/python3 ${./steam-colors/bridge.py} --css ${./steam-colors/theme.css} "$@"
  '';
in {
  # Steam and Decky are top-only; book has no native Steam client.
  home-manager.users.${user}.systemd.user.services.steam-system-colors = {
    Unit = {
      Description = "Apply KDE palette notifications to Steam";
      After = [ "graphical-session.target" ];
      PartOf = [ "graphical-session.target" ];
      ConditionEnvironment = "KDE_FULL_SESSION=true";
    };
    Service = {
      ExecStart = bridge;
      Restart = "on-failure";
      RestartSec = 3;
    };
    Install.WantedBy = [ "graphical-session.target" ];
  };
}
