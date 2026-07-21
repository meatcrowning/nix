{ config, pkgs, lib, ... }:

{
  xdg.configFile."kitty/kitty.conf".source = ./kitty-files/kitty.conf;

  # Listener that greys an unfocused kitty's foreground to match filer / the
  # hyprvtb inactive tone. kitty can't self-detect OS focus under Hyprland, so
  # this is driven off Hyprland's event socket via `kitty @ set-colors`. Started
  # from hyprland.lua's autostart (needs the live HYPRLAND_INSTANCE_SIGNATURE).
  xdg.configFile."kitty/kitty-focus-dim.py".source = ./kitty-files/kitty-focus-dim.py;

  # Startup session: a background launch of the hyprvtb titlebar-button client
  # (~/nix/pylib/kitty-vtb.py, run from the live repo) plus the normal shell
  # window. See the startup_session note in kitty.conf.
  xdg.configFile."kitty/vtb.session".source = ./kitty-files/vtb.session;

  # theme.conf is fully rewritten (plain `cat >`) by wal-set.sh on every
  # wallpaper change — needs to be a real writable file, seeded once, not a
  # read-only Nix-store symlink.
  home.activation.seedKittyTheme = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    [ -e "$HOME/.config/kitty/theme.conf" ] || install -D -m644 ${./kitty-files/theme.conf} "$HOME/.config/kitty/theme.conf"
  '';
}
