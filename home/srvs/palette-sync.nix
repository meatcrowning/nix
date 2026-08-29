{ pkgs, lib, ... }:

# Keep the wallpaper colour-theme knobs level across `top` and `book`.
#
# The palette comes out of the wallpaper, but HOW it comes out is settings, and
# those were machine-local: the same picture produced a purple Plasma scheme on
# top and a blue-grey one on book, purely because paletteVariant/
# paletteColorCount/paletteDropped had drifted apart. The script carries the
# reasoning and the file-per-host rule; this module is only its plumbing.
#
# Transport is docs/, which already syncs both ways every 5 minutes — no new
# remote, no new credentials. Both machines get this: `home/` is shared verbatim
# and Fedora Asahi runs systemd the same as NixOS.

{
  xdg.configFile."scripts/palette-sync.py" = {
    source = ./palette-sync-files/palette-sync.py;
    executable = true;
  };

  systemd.user.services.palette-sync = {
    Unit = {
      Description = "Sync the wallpaper colour-theme settings across machines";
      # The path unit fires on every settings.json write, and the panel writes
      # it for gamma, view mode and a bar drag as well — a rate-limited start
      # would trip and stay dead, so there is no rate limit to trip.
      StartLimitIntervalSec = 0;
    };
    Service = {
      Type = "oneshot";
      Environment = [ "PATH=${lib.makeBinPath [ pkgs.coreutils ]}" ];
      ExecStart = "${pkgs.python3}/bin/python3 %h/.config/scripts/palette-sync.py";
    };
  };

  # Publish quickly: an edit made in the Settings window should be in docs/
  # before the next 5-minute docs tick carries it, not after it.
  systemd.user.paths.palette-sync = {
    Unit.Description = "Watch settings.json for a colour-theme change";
    Path.PathModified = "%h/.config/quickshell/settings.json";
    Install.WantedBy = [ "paths.target" ];
  };

  # And notice the OTHER machine's file, which arrives with no local write to
  # watch for.
  systemd.user.timers.palette-sync = {
    Unit.Description = "Periodically reconcile the colour-theme settings";
    Timer = {
      # OnStartupSec must accompany OnBootSec in a user manager — see
      # nix-docs.nix for the incident that rule came from.
      OnBootSec = "4min";
      OnStartupSec = "4min";
      OnUnitActiveSec = "5min";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
