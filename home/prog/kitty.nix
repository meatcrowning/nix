{ config, pkgs, lib, ... }:

{
  xdg.configFile."kitty/kitty.conf".source = ./kitty-files/kitty.conf;

  # Focus-dim watcher (kitty.conf `watcher focus-dim.py`): greys the foreground
  # when the terminal is unfocused, matching filer / the hyprvtb inactive tone.
  xdg.configFile."kitty/focus-dim.py".source = ./kitty-files/focus-dim.py;

  # theme.conf is fully rewritten (plain `cat >`) by wal-set.sh on every
  # wallpaper change — needs to be a real writable file, seeded once, not a
  # read-only Nix-store symlink.
  home.activation.seedKittyTheme = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    [ -e "$HOME/.config/kitty/theme.conf" ] || install -D -m644 ${./kitty-files/theme.conf} "$HOME/.config/kitty/theme.conf"
  '';
}
