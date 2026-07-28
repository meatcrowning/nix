{ config, pkgs, lib, ... }:

{
  # kitty.conf must resolve to a real file inside its OWN store directory, not
  # to a bare top-level store file: kitty ≥0.47's config watcher (`kitten
  # __watch_conf__`) fully resolves the symlink chain and RECURSIVELY inotify-
  # watches the resolved file's parent directory. With a plain
  # `source = ./kitty-files/kitty.conf` that parent is /nix/store itself, so
  # every kitty instance pinned ~250k watches (one per store dir, growing with
  # each build) and exhausted fs.inotify.max_user_watches — which is what
  # silently killed Quickshell hot-reload on book. The wrapper dir must contain
  # a COPY, not a symlink (linkFarm would resolve straight back to the store
  # root).
  xdg.configFile."kitty/kitty.conf".source =
    "${pkgs.runCommandLocal "kitty-conf" { } ''
      mkdir -p $out
      cp ${./kitty-files/kitty.conf} $out/kitty.conf
    ''}/kitty.conf";

  # Listener that greys an unfocused kitty's foreground to match filer / the
  # hyprvtb inactive tone. kitty can't self-detect OS focus under Hyprland, so
  # this is driven off Hyprland's event socket via `kitty @ set-colors`. Started
  # from hyprland.lua's autostart (needs the live HYPRLAND_INSTANCE_SIGNATURE).
  xdg.configFile."kitty/kitty-focus-dim.py".source = ./kitty-files/kitty-focus-dim.py;

  # Startup session: a background launch of the hyprvtb titlebar-button client
  # (~/nix/apps/pylib/kitty-vtb.py, run from the live repo) plus the normal shell
  # window. See the startup_session note in kitty.conf.
  xdg.configFile."kitty/vtb.session".source = ./kitty-files/vtb.session;

  # theme.conf is fully rewritten (plain `cat >`) by wal-set.sh on every
  # wallpaper change — needs to be a real writable file, seeded once, not a
  # read-only Nix-store symlink.
  home.activation.seedKittyTheme = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    [ -e "$HOME/.config/kitty/theme.conf" ] || install -D -m644 ${./kitty-files/theme.conf} "$HOME/.config/kitty/theme.conf"
  '';
}
