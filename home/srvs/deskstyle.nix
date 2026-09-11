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
      # PartOf, not just WantedBy: this service branches on the session it was
      # started in (kdetheme.is_plasma reads XDG_CURRENT_DESKTOP once, from its
      # own environment). WantedBy alone starts it at the first session and
      # then leaves it running across a logout into a DIFFERENT session, still
      # answering with the old session's answer. On 2026-09-10 an instance
      # started under labwc survived into Plasma and sent every wallpaper
      # change down the non-Plasma path: plasmashell never heard about it and
      # kdeglobals' widgetStyle was reset to Breeze. PartOf stops it with the
      # session's target so the next login starts a fresh one that knows where
      # it is.
      PartOf = [ "graphical-session.target" ];
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
