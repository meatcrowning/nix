{ pkgs, lib, config, ... }:

# The loopback courier behind Vivaldi's live 4chan and Twitter/X page themes.
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
      Description = "Serve this desktop's live browser-theme CSS on 127.0.0.1";
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

  # The open-tab sheet above is live, but its embedded fallback must track a
  # generator change too.  Keep the managed Tampermonkey source current
  # without asking for a manual `chan-theme` run or a browser restart.
  systemd.user.services.chan-theme-script = {
    Unit.Description = "Regenerate the desktop 4chan userscript";
    Service = {
      Type = "oneshot";
      ExecStart = "${pkgs.python3}/bin/python3 /home/lam/nix/apps/pylib/tools/chan-userscript.py";
    };
  };

  systemd.user.paths.chan-theme-script = {
    Unit.Description = "Watch the desktop 4chan userscript sources";
    Path = {
      PathChanged = [
        "%h/nix/apps/pylib/chantheme.py"
        "%h/nix/apps/pylib/chansource.py"
        "%h/nix/apps/pylib/twittertheme.py"
        "%h/nix/apps/pylib/userscript.py"
        "%h/nix/apps/pylib/tools/chan-userscript.py"
      ];
      Unit = "chan-theme-script.service";
    };
    Install.WantedBy = [ "paths.target" ];
  };

  # Vivaldi's OWN UI (panels, settings, the tab stack) is a Chromium page too:
  # `apps/pylib/vivaldichrome.py` re-themes the whole chrome by defining the
  # ~90 CSS custom properties its theme engine reads, and the scrollbar sheet
  # rides in the same file — but it is a `custom.css` Vivaldi reads at STARTUP,
  # so it cannot poll the courier the way a userscript does. Nothing
  # else can keep it current either: the palette moves when wal-set.sh rewrites
  # Theme.qml or when the KDE scheme changes, neither of which Vivaldi sees.
  # So a path unit watches those two files and re-mints the css; whenever he
  # next launches Vivaldi, what it reads is current. Unchanged content is not
  # rewritten, so a run that changes nothing costs nothing.
  systemd.user.services.vivaldi-ui-css = {
    Unit = {
      Description = "Mint Vivaldi's custom.css from the live palette";
      # No start limit, because the trigger is a BURST. wal-set.sh rewrites
      # Theme.qml and then the KDE scheme in one pass, and each write starts
      # this unit — five starts inside ten seconds is systemd's default ceiling
      # and the run trips it. What made that more than cosmetic: the unit is
      # then FAILED, its path unit fails with it, and the LAST write of the
      # burst — the kdeglobals one that carries the new colour — reaches
      # nothing. Measured on book 2026-08-28: Vivaldi and Konsole stayed green
      # while the whole rest of the desktop went purple, and neither watcher
      # would have fired again until the next rebuild.
      StartLimitIntervalSec = 0;
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${pkgs.python3}/bin/python3 /home/lam/nix/apps/pylib/tools/vivaldi-theme.py --ui";
      TimeoutStartSec = "1min";
    };
    Install.WantedBy = [ "default.target" ];
  };

  systemd.user.paths.vivaldi-ui-css = {
    Unit.Description = "Watch the palette sources Vivaldi's custom.css is built from";
    Path = {
      PathChanged = [
        "%h/.config/quickshell/Theme.qml"      # the Hyprland face
        "%h/.config/kdeglobals"                # the Plasma one
        "/home/lam/nix/apps/pylib/scrollcss.py"       # scrollbar geometry
        "/home/lam/nix/apps/pylib/vivaldichrome.py"   # Vivaldi chrome
        "/home/lam/nix/apps/pylib/tools/vivaldi-theme.py" # its writer
      ];
      Unit = "vivaldi-ui-css.service";
    };
    Install.WantedBy = [ "paths.target" ];
  };

  # An internal Start Page is not inside custom.css at all: Vivaldi reads its
  # background from the selected theme's Preferences entry.  It owns that file
  # while running, so writing it then would be lost at shutdown.  Watch its
  # SingletonLock instead: creation is harmless (the helper deliberately
  # skips a live profile), and deletion occurs after Vivaldi's final Prefs
  # flush, when the helper can safely make the next launch current.  This is
  # the missing automatic hand-off for the Start Page; no manual theme command
  # is needed after a normal browser close.
  systemd.user.services.vivaldi-theme-prefs = {
    Unit.Description = "Refresh Vivaldi's saved desktop theme after exit";
    Service = {
      Type = "oneshot";
      # A fast close/reopen can remove and recreate SingletonLock between two
      # inotify deliveries.  Once either delivery starts us, wait on the lock
      # itself instead of trusting a second event, then write after the final
      # preferences flush.  `-L`, rather than `-e`, matters: Chromium's lock
      # is a deliberately dangling hostname-pid symlink.
      ExecStart = "${pkgs.bash}/bin/bash -c 'while test -L ${config.home.homeDirectory}/.config/vivaldi/SingletonLock || test -L ${config.home.homeDirectory}/.var/app/com.vivaldi.Vivaldi/config/vivaldi/SingletonLock; do ${pkgs.coreutils}/bin/sleep 2; done; exec ${pkgs.python3}/bin/python3 /home/lam/nix/apps/pylib/tools/vivaldi-theme.py --prefs'";
      TimeoutStartSec = "infinity";
    };
  };

  systemd.user.paths.vivaldi-theme-prefs = {
    Unit.Description = "Apply Vivaldi's Start Page theme when its profile closes";
    Path = {
      PathChanged = [
        "%h/.config/vivaldi/SingletonLock"
        "%h/.var/app/com.vivaldi.Vivaldi/config/vivaldi/SingletonLock"
      ];
      Unit = "vivaldi-theme-prefs.service";
    };
    Install.WantedBy = [ "paths.target" ];
  };
}
