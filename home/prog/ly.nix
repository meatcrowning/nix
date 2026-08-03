{ lib, host, ... }:

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
  # ly reads ~/.config/ly/config.ini (via --config, see the drop-in). The
  # override restates Fedora's three real customizations and points
  # waylandsessions at the session dir below; everything else stays at ly's
  # compiled defaults, which match the stock config.
  xdg.configFile."ly/config.ini".source = ./ly-files/config.ini;

  # ly exits at startup when the lang file is missing from its config dir; the
  # stub parses to the compiled English strings (same as Fedora's en.ini).
  xdg.configFile."ly/lang/en.ini".source = ./ly-files/lang/en.ini;

  # The supervised Hyprland session — Exec is hypr-supervise instead of
  # /usr/bin/start-hyprland. The greeter's other sessions stay available via
  # the activation step below (pure eval cannot read the system files as
  # `source`; the copy happens impurely at switch time instead).
  xdg.configFile."ly/wayland-sessions/hyprland.desktop".source = ./ly-files/wayland-sessions/hyprland.desktop;

  # Fedora's other wayland sessions, refreshed into the same dir on every
  # switch so the greeter keeps offering them (a future dnf update that adds
  # or renames a session entry shows up at the next switch).
  home.activation.lySessionEntries = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    mkdir -p "$HOME/.config/ly/wayland-sessions"
    for f in hyprland-uwsm.desktop plasma.desktop; do
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
