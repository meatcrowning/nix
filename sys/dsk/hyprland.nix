{ config, lib, pkgs, inputs, ... }:

let
  hyprPkg = inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system}.hyprland;

  # The session's entry point, in place of Hyprland's own `start-hyprland`.
  #
  # start-hyprland is a watchdog: when the compositor exits uncleanly it
  # restarts it **with `--safe-mode`**, i.e. with no config at all — no
  # titlebars, no keybinds, no panel, no autostart — and the only way out is a
  # relog. That is a sane default for "the user's config is broken", and the
  # wrong answer here, because the thing most likely to take this compositor
  # down is a freshly built hyprvtb being hot-swapped in by `hyprctl reload`
  # (see home/prog/hyprvtb/tools/hotswap-test.sh). Losing the entire desktop
  # environment — rather than just the new plugin — turns a bad build into an
  # emergency instead of a debugging session.
  #
  # So: same restart, different policy. Name the plugin build that was live
  # when it died (hyprland.lua wrote it to state/loaded, this copies it to
  # state/crashed-with) and come back with the REAL config. hyprland.lua reads
  # that breadcrumb on the way up and loads the last known-good build instead
  # of the one that just crashed, so the session returns intact, one plugin
  # version behind, with ~/.local/state/hyprvtb/quarantined saying why.
  #
  # After 3 crashes it stops guessing and hands over to Hyprland's own
  # watchdog, safe mode and all — at that point the problem is not the plugin.
  superviseFor = pkg: pkgs.writeShellScript "hypr-supervise" ''
    set -u
    STATE="''${XDG_STATE_HOME:-$HOME/.local/state}/hyprvtb"
    LOG="$STATE/supervise.log"
    mkdir -p "$STATE"
    say() { printf '%s %s\n' "$(${pkgs.coreutils}/bin/date -Is)" "$*" >> "$LOG"; }

    tries=0
    while :; do
      say "starting Hyprland (restarts so far: $tries)"
      ${pkg}/bin/Hyprland "$@"
      rc=$?

      if [ "$rc" = 0 ]; then
        say "clean exit — session over"
        exit 0
      fi

      if [ -s "$STATE/loaded" ]; then
        cp "$STATE/loaded" "$STATE/crashed-with"
        say "UNCLEAN exit (rc=$rc) — blaming plugin $(cat "$STATE/loaded")"
      else
        say "UNCLEAN exit (rc=$rc) — no plugin was recorded as loaded"
      fi

      tries=$((tries + 1))
      if [ "$tries" -ge 3 ]; then
        say "3 crashes in one session — handing over to start-hyprland (safe mode)"
        exec ${pkg}/bin/start-hyprland "$@"
      fi
      sleep 1
    done
  '';

  # Same package, one file different: the wayland-session entry points at the
  # supervisor above instead of start-hyprland. Overriding programs.hyprland's
  # package (rather than adding a second sessionPackage) keeps ONE "Hyprland"
  # entry in the display manager — the module does
  # `services.displayManager.sessionPackages = [ cfg.package ]`, and two
  # identically-named sessions is a coin flip for which one the user gets.
  #
  # The two passthru attributes are what make that survivable:
  #   - mainProgram, because the module's setuid wrapper resolves the
  #     compositor with `lib.getExe cfg.package`;
  #   - override, because the module runs every package option through
  #     genFinalPackage (nixos/modules/programs/wayland/lib.nix), which calls
  #     `.override { enableXWayland = ...; }` when the argument exists. Without
  #     it the eval fails outright ("attribute 'override' missing"); delegating
  #     it naively would hand the module the RAW hyprland back and silently
  #     drop the rewritten session entry. So re-wrap the overridden package.
  wrapSession = pkg:
    let
      joined = pkgs.symlinkJoin {
        name = "hyprland-supervised";
        paths = [ pkg ];
        postBuild = ''
          rm -f $out/share/wayland-sessions/hyprland.desktop
          cat > $out/share/wayland-sessions/hyprland.desktop <<EOF
          [Desktop Entry]
          Name=Hyprland
          Comment=An intelligent dynamic tiling Wayland compositor
          Exec=${superviseFor pkg}
          Type=Application
          DesktopNames=Hyprland
          Keywords=tiling;wayland;compositor;
          EOF
        '';
        meta = pkg.meta // { mainProgram = "Hyprland"; };
      };
    in
    # Start from the ORIGINAL package's attribute set, then let the join's
    # outputs win. A symlinkJoin on its own is missing everything the rest of
    # the module system reads off a package — version, pname, the man/dev
    # outputs, meta — and each one only shows up as its own eval error
    # ("attribute 'man' missing", then 'version', ...). Inheriting the lot and
    # overriding just what the join replaces gets all of them at once.
    pkg // joined // {
      meta = pkg.meta // { mainProgram = "Hyprland"; };
      override = args: wrapSession (pkg.override args);
      # sessionPackages' type demands this: it is how the display-manager
      # module knows which session names a package provides.
      providedSessions = pkg.providedSessions or [ "hyprland" ];
      # hyprland is multi-output (out, man, dev) and a symlinkJoin is not —
      # pass the other outputs straight through.
      outputs = pkg.outputs;
    } // lib.genAttrs (lib.remove "out" pkg.outputs) (o: pkg.${o});

  hyprSupervised = wrapSession hyprPkg;

in
{
  # Hyprland comes from the pinned `hyprland` flake input, NOT nixpkgs — see
  # the long comment on that input in flake.nix. Short version: hyprvtb is
  # built against Hyprland's internal headers, so an unpinned compositor
  # meant every unrelated `nix flake update` could break the desktop's
  # titlebars (and with them filer/viewer/player/surfer's entire chrome).
  # Bump deliberately, following the ritual in home/prog/hyprvtb/PORTING.md.
  programs.hyprland = {
    enable = true;
    package = hyprSupervised; # = the pinned hyprland, session entry rewritten (see above)
    portalPackage = inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system}.xdg-desktop-portal-hyprland;
  };

  # xdg-desktop-portal routing for the Hyprland session. programs.hyprland
  # already enables xdg.portal + the hyprland backend; without an explicit
  # config, routing falls back to the hyprland-portals.conf shipped inside
  # xdph. Make it explicit: screencast/screenshot go to the hyprland backend,
  # file dialogs + the dark-mode Settings signal go to KDE (so they match the
  # kdeglobals/wal theming), and gtk is the general fallback for everything
  # else. All these backends are already present on the system (Plasma pulls
  # in -kde/-gtk); this only picks who answers which interface.
  # Written to /etc/xdg-desktop-portal/hyprland-portals.conf (used when
  # $XDG_CURRENT_DESKTOP contains "hyprland", which the session sets).
  xdg.portal.config.hyprland = {
    default = [ "hyprland" "gtk" ];
    "org.freedesktop.impl.portal.FileChooser" = [ "kde" ];
    "org.freedesktop.impl.portal.Settings" = [ "kde" ];
  };

  # Lock.qml (quickshell/Lock.qml) authenticates through this PAM service by
  # name (PamContext { config: "quickshell-lock" }) — without it declared,
  # PAM has nothing to open for that service name and Lock.qml reports "auth
  # unavailable". Empty options give the same baseline pam_unix stack NixOS
  # already generates for swaylock/vlock (see /etc/pam.d/swaylock) — plain
  # password auth, no desktop-environment dependency, matching what the
  # migration source's quickshell-lock.pam (written for Fedora's system-auth
  # include, which doesn't exist on NixOS) was actually going for.
  security.pam.services.quickshell-lock = {};
}
