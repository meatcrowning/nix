{ pkgs, ... }:

# The D-Bus coordinator is deliberately installed on both hosts.  Its Python
# source is live, but the interpreter is pinned here because D-Bus services get
# a minimal environment and must not depend on a GUI application's wrapper.
let
  deskstylePython = pkgs.python3.withPackages (ps: [ ps.pygobject3 ]);
in
{
  systemd.user.services.deskstyle = {
    Unit = {
      Description = "Coordinate one live desktop appearance transaction";
      After = [ "graphical-session.target" ];
      StartLimitIntervalSec = 0;
    };
    Service = {
      Type = "simple";
      ExecStart = "${deskstylePython}/bin/python3 /home/lam/nix/home/srvs/deskstyle-files/deskstyle-service.py";
      Restart = "on-failure";
      RestartSec = 2;
    };
    Install.WantedBy = [ "graphical-session.target" ];
  };
}
