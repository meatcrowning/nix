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
  # cursor-recolor.sh needs xcur2png/xcursorgen/magick, which aren't on the bare
  # system PATH it inherits when Quickshell spawns wal-set.sh. Bake their store
  # bin dirs into the script's PATH (@toolPath@ placeholder) so it always resolves.
  cursorTools = lib.makeBinPath [ pkgs.xcur2png pkgs.xcursorgen pkgs.imagemagick ];
  cursorRecolor = pkgs.runCommand "cursor-recolor.sh" { } ''
    substitute ${./wal-files/cursor-recolor.sh} $out \
      --replace-fail "@toolPath@" "${cursorTools}"
    chmod +x $out
  '';
  # rgb-set.py drives the OpenRGB SDK server (openrgb.service, enabled via
  # hardware.openrgb.enable on top) to keep the DRAM/motherboard RGB on the
  # wallpaper accent. Same shebang trick as wal-extract.py: exec'd directly
  # from wal-set.sh, so bake an interpreter that has openrgb-python.
  rgbPython = pkgs.python3.withPackages (ps: [ ps.openrgb-python ]);
  rgbSet = pkgs.runCommand "rgb-set.py" { } ''
    substitute ${./wal-files/rgb-set.py} $out \
      --replace-fail "/usr/bin/env python3" "${rgbPython}/bin/python3"
    chmod +x $out
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
    "scripts/wal-repo-sync.sh" = {
      source = ./wal-files/wal-repo-sync.sh;
      executable = true;
    };
    "scripts/cursor-recolor.sh" = {
      source = cursorRecolor;
      executable = true;
    };
    "scripts/ly-theme.sh" = {
      # The ly login greeter's colours (top only: /var/lib/ly/config.ini is
      # seeded by sys/dsk/plasma.nix's activation; on book the file does not
      # exist and the script no-ops). wal-set.sh calls it on every palette
      # change so the greeter follows the wallpaper at next login.
      source = ./wal-files/ly-theme.sh;
      executable = true;
    };
    "scripts/rgb-set.py" = {
      source = rgbSet;
      executable = true;
    };
  };

  # cursor-recolor.sh (called from wal-set.sh) decompiles the GoogleDot-Black
  # cursor theme with xcur2png, recolours the frames with ImageMagick (in
  # home/pkgs/media/process.nix), and recompiles with xcursorgen.
  home.packages = with pkgs; [ xcur2png xcursorgen ];

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

  # wal-set.sh drives the live compositor (`hyprctl eval hl.config{…}` for the
  # border colours, `hyprctl setcursor` inside cursor-recolor.sh), so it is the
  # one unit here that must NOT inherit the systemd user manager's
  # HYPRLAND_INSTANCE_SIGNATURE / WAYLAND_DISPLAY: every Hyprland process on the
  # machine overwrites that store, and a SIGKILLed nested test compositor leaves
  # its dead signature there for the rest of the login (see hypr-env.nix). Under
  # a stale signature every hyprctl call fails to connect and the unit still
  # exits 0 — the wallpaper changes, the theme does not, nothing is logged.
  # hypr-session-env.sh resolves the instance that is actually alive.
  systemd.user.services.wal-set = {
    Unit = {
      Description = "Re-tile the wallpaper and recolour the desktop from ~/.config/wall.png";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "oneshot";
      ExecStart = "%h/.config/scripts/hypr-session-env.sh %h/.config/scripts/wal-set.sh";
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

  # Auto-version wallpapers dropped into ~/Pictures/wall: copy them into the
  # repo's wallpaper set and commit + push (see wal-repo-sync.sh for the paranoid
  # git handling). PATH is pinned so the service finds git + gh (the credential
  # helper is `!gh auth git-credential`, so gh must be resolvable) without
  # depending on the ambient systemd-user PATH.
  systemd.user.services.wal-repo-sync = {
    Unit = {
      Description = "Commit + push wallpapers dropped into ~/Pictures/wall to the nix repo";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "oneshot";
      # findutils for xargs: sync_index() clears phantom staged deletions with
      # `git diff -z | xargs -0 git reset`, and coreutils has no xargs — without
      # it every sync left the committed wallpaper staged-for-deletion in the
      # shared index.
      Environment = [ "PATH=${lib.makeBinPath [ pkgs.git pkgs.gh pkgs.coreutils pkgs.findutils ]}" ];
      ExecStart = "%h/.config/scripts/wal-repo-sync.sh";
    };
  };

  systemd.user.paths.wal-repo-sync = {
    Unit.Description = "Watch ~/Pictures/wall and sync new wallpapers into the nix repo";
    Path.PathModified = "%h/Pictures/wall";
    Install.WantedBy = [ "default.target" ];
  };
}
