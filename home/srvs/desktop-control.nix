{ pkgs, ... }:

# A persistent desktop-session broker.  Chatter talks to its Unix socket instead
# of launching a GUI process through the bounded code runner, whose timeout
# kills the whole child process group.
{
  xdg.configFile."scripts/oracle-desktop-control.py" = {
    source = ../../apps/oracle/tools/desktop-control-service.py;
    executable = true;
  };

  systemd.user.services.oracle-desktop-control = {
    Unit = {
      Description = "Chatter desktop-control broker";
      After = [ "graphical-session.target" ];
    };
    Service = {
      ExecStart = "${pkgs.python3}/bin/python3 %h/.config/scripts/oracle-desktop-control.py";
      Restart = "on-failure";
      RestartSec = 1;
    };
    Install.WantedBy = [ "default.target" ];
  };
}
