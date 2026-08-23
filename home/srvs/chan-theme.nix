{ pkgs, lib, config, ... }:

# The loopback courier behind the Vivaldi 4chan re-skin — what makes it LIVE.
#
# surfer serves that sheet to its own pages in-process (`surferonee://`).
# Vivaldi is somebody else's browser: the only injection seat is Tampermonkey,
# and a userscript has no Python to ask, so the CSS used to be BAKED into
# `~/.local/share/chan-theme/desktop-4chan.user.js` and went stale the moment
# the colour scheme or the wallpaper moved — `chan-theme` (home/prog/chan-theme.nix)
# existed purely to re-bake it by hand.
#
# This is the Python the userscript CAN ask: one stdlib HTTP server on
# 127.0.0.1:8791 serving `/chan.css`, rebuilt from the live palette on every
# request. Nothing has to notify it — not wal-set.sh, not a colour-scheme
# change, not a rebuild — because it never caches; the script polls with an
# ETag and re-adopts only when the palette has actually moved. The bake stays,
# as the fallback sheet inside the script for a page loaded while this is down.
#
# LOOPBACK ONLY. It binds 127.0.0.1, takes no parameters and can emit nothing
# but a stylesheet this repo generated, so it is NOT a firewall decision (see
# AGENTS.md, "Off-LAN: the tailnet" — anything loopback-pinned stays pinned).
#
# Live source at apps/pylib/tools/chan-theme-server.py (absolute path, valid on
# both machines); a change there needs a `systemctl --user restart
# chan-theme.service`, not a rebuild. Both hosts: the palette source follows
# `kdetheme.is_plasma()` at request time, so the same unit answers with the KDE
# scheme in a Plasma session and the wallpaper palette in the Hyprland one.
{
  systemd.user.services.chan-theme = {
    Unit = {
      Description = "Serve this desktop's 4chan re-skin CSS on 127.0.0.1";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "simple";
      # Same pinned-PATH shape as the other live-source units: the ambient
      # systemd-user PATH reaches nothing, and python3 is a full store path.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
      ];
      ExecStart = "${pkgs.python3}/bin/python3 /home/lam/nix/apps/pylib/tools/chan-theme-server.py";
      Restart = "on-failure";
      RestartSec = "10s";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
