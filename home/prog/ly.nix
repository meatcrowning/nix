{ lib, pkgs, host, ... }:

# book's Hyprland session gets the same crash net top has — there it is
# sys/dsk/hyprland.nix, which rewrites the NixOS wayland-session entry so the
# session starts under a supervisor that quarantines a crashed plugin build
# instead of letting start-hyprland come back in --safe-mode. book runs
# Fedora's ly display manager, and ly only lists sessions from the dirs its
# config names, so the net here is a per-user session dir + a ly config that
# points at it, selected by a systemd drop-in (the one root step,
# tools/install-ly-supervision.sh). Air-only: top's session is owned by its
# NixOS module. Runbook: docs/agents/book-supervised-session.md.
lib.mkIf (host == "air") {
  # ly reads ~/.config/ly/config.ini (via --config, see the drop-in) as the
  # confined xdm_t SELinux domain, which has no rule to read /nix/store
  # (label default_t) — a plain xdg.configFile symlink into the store is
  # silently unreadable there (AVC: denied { read } ... tcontext=default_t),
  # so ly falls back to its compiled defaults and the override does nothing.
  # Copy these out of the store as plain files instead, so they land as
  # ordinary config_home_t content ly can actually read. The override restates
  # Fedora's three real customizations and points waylandsessions at the
  # session dir below; everything else stays at ly's compiled defaults,
  # which match the stock config.
  #
  # ly exits at startup when the lang file is missing from its config dir;
  # the stub parses to the compiled English strings (same as Fedora's
  # en.ini). The wayland-sessions entry's Exec is hypr-supervise instead of
  # /usr/bin/start-hyprland.
  #
  # console-font.psf.gz is the greeter's TEXT SIZE. ly is a TUI on the
  # framebuffer console, so the only lever is the console font: at the kernel's
  # default 8x16 on book's 2560x1600 panel the greeter renders 320 columns of
  # near-invisible text, while the Hyprland session it hands over to runs at
  # scale 1.67. Terminus 14x28 (ter-128n) is 1.75x that default — the closest
  # available step to the session's scale, and still 182x57 characters, far
  # more than ly's box needs. tools/install-ly-supervision.sh copies it on to
  # /usr/lib/kbd/consolefonts (lib_t, readable from any domain — under $HOME or
  # in the store it is a read the confined greeter may be denied, the same trap
  # config.ini hit) and adds the setfont that loads it; re-run that installer
  # after a terminus bump to refresh the system copy.
  home.activation.lyPlainConfig = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    mkdir -p "$HOME/.config/ly/lang" "$HOME/.config/ly/wayland-sessions"
    cp -f ${./ly-files/config.ini} "$HOME/.config/ly/config.ini"
    cp -f ${./ly-files/lang/en.ini} "$HOME/.config/ly/lang/en.ini"
    cp -f ${./ly-files/wayland-sessions/hyprland.desktop} "$HOME/.config/ly/wayland-sessions/hyprland.desktop"
    cp -f ${pkgs.terminus_font}/share/consolefonts/ter-128n.psf.gz "$HOME/.config/ly/console-font.psf.gz"
  '';

  # Fedora's other wayland sessions, refreshed into the same dir on every
  # switch so the greeter keeps offering them (a future dnf update that adds
  # or renames a session entry shows up at the next switch).
  #
  # This list is an ALLOWLIST, not a mirror: `waylandsessions` above points ly
  # at this directory instead of /usr/share/wayland-sessions, so a session
  # installed into Fedora's prefix does NOT appear in the greeter until its
  # entry is named here. AeroThemePlasma (installed from source on book,
  # 2026-08-28) was invisible for exactly that reason, with the .desktop file
  # sitting correctly in /usr/share/wayland-sessions the whole time.
  home.activation.lySessionEntries = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    mkdir -p "$HOME/.config/ly/wayland-sessions"
    for f in hyprland-uwsm.desktop plasma.desktop aerothemeplasma.desktop; do
      [ -f "/usr/share/wayland-sessions/$f" ] && cp -f "/usr/share/wayland-sessions/$f" "$HOME/.config/ly/wayland-sessions/$f"
    done
  '';

  # The wrapper the desktop entry Exec's, at the stable absolute path the
  # entry names. Exercised by tools/hypr-supervise-test.sh.
  home.file.".local/bin/hypr-supervise" = {
    source = ./ly-files/hypr-supervise;
    executable = true;
  };
}
