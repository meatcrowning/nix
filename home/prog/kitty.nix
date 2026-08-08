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

  # Desktop-notification filter: kitty runs this file's main() for every OSC
  # 99 / OSC 777 notification a program inside it raises, and drops the ones it
  # returns True for. It exists because Claude Code re-raises its "Claude is
  # waiting for your input" notification every ~60s for as long as a session
  # sits idle, with a fresh random id each time so kitty cannot coalesce them —
  # the file's header has the full story and the two rules. Not watched by
  # `kitten __watch_conf__` (that only follows `all_config_paths`, i.e.
  # kitty.conf and its includes), so a plain store symlink is safe here.
  # Loaded once per kitty PROCESS: already-running kitties keep the old
  # behaviour until they are restarted.
  xdg.configFile."kitty/notifications.py".source = ./kitty-files/notifications.py;

  # Splits-layout drag fix: kitty.conf's `watcher` line loads this into every
  # kitty process, where it monkeypatches Splits.drag_resize_window so a
  # border drag moves only the grabbed handle (see the file's header). Like
  # notifications.py it is not followed by `kitten __watch_conf__`, so a plain
  # store symlink is safe. Both hosts — book's Fedora kitty reads the same
  # config dir, which is why this is a watcher and not a package patch.
  xdg.configFile."kitty/free-handles.py".source = ./kitty-files/free-handles.py;

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

  # font.conf is the pixel-font include that kitty.conf pulls in and that
  # apply-pixel-font.sh regenerates from settings.json. Seeded once so the
  # include never resolves to nothing on a machine that has not run
  # apply-pixel-font.sh yet (a missing include is an error, not a no-op, in
  # kitty). The pick value wins from the first apply-pixel-font.sh run.
  home.activation.seedKittyFont = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    if [ ! -e "$HOME/.config/kitty/font.conf" ]; then
      printf 'font_family More Perfect DOS VGA\nfont_size 11\n' > "$HOME/.config/kitty/font.conf"
      chmod 644 "$HOME/.config/kitty/font.conf"
    fi
  '';
}
