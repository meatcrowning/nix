{ config, pkgs, lib, ... }:

let
  pillowPython = pkgs.python3.withPackages (ps: [ ps.pillow ]);
  # wal-prepare.sh execs this directly (not via `python3 ...`), so its own
  # shebang has to resolve to an interpreter with Pillow, without adding a
  # second `python3` to home.packages (would collide with the plain one in
  # home/pkgs/dev.nix).
  walExtract = pkgs.runCommand "wal-extract.py" { } ''
    substitute ${./wal-files/wal-extract.py} $out \
      --replace-fail "/usr/bin/env python3" "${pillowPython}/bin/python3"
  '';
in
{
  xdg.configFile = {
    "scripts/wal-set.sh" = {
      source = ./wal-files/wal-set.sh;
      executable = true;
    };
    "scripts/wal-prepare.sh" = {
      source = ./wal-files/wal-prepare.sh;
      executable = true;
    };
    "scripts/wal-prepare-all.sh" = {
      source = ./wal-files/wal-prepare-all.sh;
      executable = true;
    };
    "scripts/resize-mode-notify.sh" = {
      source = ./wal-files/resize-mode-notify.sh;
      executable = true;
    };
    "scripts/wal-extract.py" = {
      source = walExtract;
      executable = true;
    };
  };

  # The wallpaper set is versioned in the repo (./wal-files/wallpapers) so it's
  # shared across machines. We *copy* (not symlink) each into ~/Pictures/wall on
  # activation, so the directory stays a real writable dir: the picker's live
  # rescan and the "drop a new wallpaper in" workflow (wal-prepare.path) keep
  # working, and the store copies aren't read-only symlinks. Existing files are
  # left untouched (`[ -e ] ||`), so hand-added or edited wallpapers survive.
  home.activation.seedWallpapers = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    mkdir -p "$HOME/Pictures/wall"
    for f in ${./wal-files/wallpapers}/*; do
      dest="$HOME/Pictures/wall/$(basename "$f")"
      [ -e "$dest" ] || install -m644 "$f" "$dest"
    done
  '';

  # wall.png is the "drop a new wallpaper here" trigger wal-set.path watches
  # for manual overwrites (cp/mv over it) — needs to be a real writable file
  # a plain `cp` can replace, not a read-only Nix-store symlink. Seed once.
  home.activation.seedWallPng = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    [ -e "$HOME/.config/wall.png" ] || install -D -m644 ${./wal-files/wall.png} "$HOME/.config/wall.png"
  '';

  systemd.user.services.wal-set = {
    Unit = {
      Description = "Re-tile the wallpaper and recolour the desktop from ~/.config/wall.png";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "oneshot";
      ExecStart = "%h/.config/scripts/wal-set.sh";
    };
  };

  systemd.user.paths.wal-set = {
    Unit.Description = "Watch ~/.config/wall.png and re-apply the wallpaper/theme on change";
    Path.PathChanged = "%h/.config/wall.png";
    Install.WantedBy = [ "default.target" ];
  };

  systemd.user.services.wal-prepare = {
    Unit = {
      Description = "Pre-cache tile/theme data for every image in ~/Pictures/wall";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "oneshot";
      ExecStart = "%h/.config/scripts/wal-prepare-all.sh";
    };
  };

  systemd.user.paths.wal-prepare = {
    Unit.Description = "Watch ~/Pictures/wall and pre-cache any new wallpaper's tile/theme";
    Path.PathModified = "%h/Pictures/wall";
    Install.WantedBy = [ "default.target" ];
  };
}
