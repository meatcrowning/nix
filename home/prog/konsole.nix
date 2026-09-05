{ pkgs, lib, config, ... }:

# Konsole's colours, kept on the system theme.
#
# Konsole is the one terminal on this box that is not kitty, and it themes
# itself out of a private `.colorscheme` file chosen per profile — it reads
# neither `kdeglobals` nor the panel's palette. So it kept drawing Breeze grey
# through every wallpaper change and every KDE colour-scheme switch, the one
# window on the desktop ignoring the theme.
#
# `konsole-theme` (live source at apps/pylib/tools/konsole-theme.py) writes
# that file from whichever palette this session calls the theme — the KDE
# colour scheme under Plasma, the panel's wallpaper palette under Hyprland,
# the same `kdetheme.is_plasma()` rule the apps and the 4chan courier follow —
# and points the DEFAULT profile at it, so a plain `konsole` gets it with
# nothing selected by hand.
#
# The path unit is what makes it dynamic: `kdeglobals` moves when he picks a
# colour scheme in System Settings, `Theme.qml` moves when wal-set.sh recolours
# the desktop from a new wallpaper. Either one repaints Konsole — including
# every window that is already open, which the file alone could never do
# (Konsole caches a colour scheme by name for the life of the process, so a
# rewritten `.colorscheme` reached only the next window). Live sessions are
# recoloured with the xterm dynamic-colour escapes instead, written to each
# session's pty; a new window still gets the file.
{
  home.packages = [
    (pkgs.writeShellScriptBin "konsole-collage" ''
      export PATH=${lib.makeBinPath [ pkgs.ffmpeg ]}:$PATH
      exec ${pkgs.python3}/bin/python3 \
        /home/lam/nix/apps/pylib/tools/konsole-collage.py "$@"
    '')
    (pkgs.writeShellScriptBin "konsole-theme" ''
      exec ${pkgs.python3}/bin/python3 \
        /home/lam/nix/apps/pylib/tools/konsole-theme.py "$@"
    '')
  ];

  systemd.user.services.konsole-theme = {
    Unit = {
      Description = "Regenerate Konsole's colour scheme from the system theme";
      After = [ "graphical-session.target" ];
      # No start limit: the trigger is a burst (Theme.qml then kdeglobals, one
      # wal-set pass), and systemd's default five-in-ten-seconds ceiling is
      # tripped by it — leaving this unit and its path unit FAILED with the
      # last write, the one carrying the new colour, unread. See chan-theme.nix
      # for the same fix and the day it was found.
      StartLimitIntervalSec = 0;
    };
    Service = {
      Type = "oneshot";
      # Same pinned-PATH shape as the other live-source units: the ambient
      # systemd-user PATH reaches nothing, and qdbus (the live re-apply) is
      # only in the user profile.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
      ];
      ExecStart = "${pkgs.python3}/bin/python3 /home/lam/nix/apps/pylib/tools/konsole-theme.py";
    };
    Install.WantedBy = [ "default.target" ];
  };

  systemd.user.paths.konsole-theme = {
    Unit.Description = "Repaint Konsole when the system theme moves";
    Path = {
      # kdeglobals is rewritten wholesale (temp+rename) by KConfig, Theme.qml
      # in place by wal-set.sh — hence both triggers on both files.
      PathChanged = [
        "%h/.config/kdeglobals"
        "%h/.config/quickshell/Theme.qml"
      ];
      PathModified = [
        "%h/.config/kdeglobals"
        "%h/.config/quickshell/Theme.qml"
      ];
    };
    Install.WantedBy = [ "default.target" ];
  };
}
