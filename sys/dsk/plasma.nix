{ config, pkgs, lib, ... }:

{
  services = {
    # Swapped SDDM for ly: SDDM's greeter is itself Wayland/DRM-capable and
    # on this NVIDIA card sometimes fails to reacquire the DRM master after
    # a Wayland compositor session ends (plausible cause of the Hyprland
    # logout hang — `hyprctl dispatch exit` kills the compositor fine, but
    # nothing visible ever happens afterward). ly is a plain TTY/framebuffer
    # greeter — it never competes for DRM/Wayland resources, so this class
    # of handoff bug shouldn't apply to it at all. Still launches Plasma the
    # same way (session .desktop files are DM-agnostic).
    displayManager.sddm.enable = false;
    displayManager.ly.enable = true;
    # The "wavy" colormix shader animation, themed to the desktop's wal
    # palette. These are the SEED colours only: the greeter's colours are
    # runtime-owned by ~/.config/scripts/ly-theme.sh (wal-set.sh on every
    # palette change), and the activation below carries them across rebuilds,
    # so these values just make the first seed match the current wallpaper.
    # Colors are 0xSSRRGGBB (SS = styling; 01 = bold).
    displayManager.ly.settings = {
      animation = "colormix";
      colormix_col1 = "0x00EBCD9B"; # accent
      colormix_col2 = "0x00544C3A"; # dim
      colormix_col3 = "0x20000000"; # near-black (hi-black style)
      fg = "0x00EBCD9B";            # input text = accent (body-text convention)
      border_fg = "0x00EBCD9B";     # box border = accent
      error_fg = "0x01DF8964";      # bold crit
    };
    desktopManager.plasma6.enable = true;
    # Hyprland is ALWAYS the default session. Plasma stays installed and
    # selectable at the greeter — it also supplies dolphin on PATH and
    # xdg-desktop-portal-kde, which the Hyprland setup uses.
    #
    # `my.aerotheme.enable` used to point this at "aerothemeplasma", which made
    # trying the theme a rebuild and leaving it another one. It now only adds
    # AeroThemePlasma to the session LIST [2026-08-28]: the aeroshell module
    # registers its session through `services.displayManager.sessionPackages`,
    # and ly reads that same `sessionData.desktops` path, so the entry appears
    # in the greeter with nothing further to wire.
    displayManager.defaultSession = "hyprland";
  };

  # Greeter theming at the system level: the ly module's config.ini is a
  # root-owned store symlink (via /etc/static) bundling load-bearing session
  # keys with the colours, so wal-set cannot write it. Point /etc/ly/config.ini
  # at a lam-writable /var/lib/ly/config.ini, re-derived from the module output
  # on every switch (session paths and commands move between store paths) with
  # the colour keys — the ones ly-theme.sh owns, keep the list in step with
  # home/srvs/wal-files/ly-theme.sh — carried forward, so a rebuild does not
  # revert the greeter to the seed colours. Failure is benign: ly falls back
  # to its defaults, login still works, and the next switch re-seeds the file.
  #
  # `sed` is spelled absolutely because an activation script's PATH does NOT
  # include it: the colour-carrying loop below failed with `sed: command not
  # found` on every single switch (12 times in the three days to 2026-08-09),
  # silently — the `[ -n "$v" ]` guard turns the failure into a no-op, so the
  # greeter quietly reverted to the seed colours each rebuild and nothing said
  # why. Any command added here needs the same treatment unless it is coreutils.
  system.activationScripts.lyRuntimeConfig = lib.stringAfter [ "etc" ] ''
    [ -f /etc/ly/config.ini ] || exit 0
    mkdir -p /var/lib/ly
    chown lam:users /var/lib/ly
    cp -f /etc/ly/config.ini /var/lib/ly/config.ini.new
    if [ -f /var/lib/ly/config.ini ]; then
      for k in border_fg colormix_col1 colormix_col2 colormix_col3 error_fg fg; do
        v="$(${pkgs.gnused}/bin/sed -n "s/^$k=//p" /var/lib/ly/config.ini | head -n1)"
        [ -n "$v" ] && ${pkgs.gnused}/bin/sed -i "s|^$k=.*|$k=$v|" /var/lib/ly/config.ini.new
      done
    fi
    chown lam:users /var/lib/ly/config.ini.new
    chmod 664 /var/lib/ly/config.ini.new
    mv -f /var/lib/ly/config.ini.new /var/lib/ly/config.ini
    ln -sfn /var/lib/ly/config.ini /etc/ly/config.ini
  '';

  # Mask DrKonqi's crash-reporter units. Under Hyprland (not a Plasma/X
  # session) the coredump *launcher* is spawned by systemd-coredump with no
  # graphical env — WAYLAND_DISPLAY/QT_QPA_PLATFORM are absent from the unit
  # — so its QGuiApplication can't init a Qt platform plugin and qFatal()s
  # on startup. That abort produces its own coredump, which gets re-processed
  # into another launcher, which aborts again: a self-amplifying loop that
  # accounted for ~75% of all recorded coredumps on this box. Masking these
  # (enable = false on a package-provided unit → Nix symlinks it to
  # /dev/null) stops the reporter from ever launching. systemd-coredump is
  # left intact, so crashes are still recorded and `coredumpctl` still works.
  systemd.services."drkonqi-coredump-processor@".enable = false;
  systemd.user.services."drkonqi-coredump-launcher@".enable = false;
  systemd.user.sockets."drkonqi-coredump-launcher".enable = false;
  # Also kill the Sentry telemetry poster — with the reporter masked there's
  # nothing to submit, and it otherwise phones crash data home to KDE's
  # Sentry. Mask its trigger (.path/.timer) and the service itself.
  systemd.user.services."drkonqi-sentry-postman".enable = false;
  systemd.user.paths."drkonqi-sentry-postman".enable = false;
  systemd.user.timers."drkonqi-sentry-postman".enable = false;

  # AeroThemePlasma — a greeter CHOICE, not a mode the machine is in. Everything
  # here is namespaced by upstream and cannot reach the Hyprland session: the
  # patched libplasma installs as ATPlasma under `io.gitgud.wackyideas.plasma.*`
  # with its `share/` stripped, and the forked shell installs as `aeroshell` /
  # `plasma-aeroshell.service` gated on `ConditionEnvironment=PLASMA_DEFAULT_SHELL
  # =io.gitgud.wackyideas.desktop`. So there is nothing to collide with, and no
  # reason to keep this behind a rebuild.
  #
  # sddm.enable is off because the greeter is ly (see above): the ATP SDDM theme
  # would pull kitemmodels in and point theme settings at a display manager that
  # is not running. polkit.enable ships a drop-in for `plasma-polkit-agent`, so
  # it reaches the Plasma sessions only — Hyprland never starts that unit.
  # x11 is off outright; KDE drops the X11 session in 6.8 and building both
  # doubles the kwin-effect compiles for a session that would never be picked.
  programs.aeroshell = lib.mkIf config.my.aerotheme.enable {
    enable = true;
    fonts.segoe.enable = true;
    fonts.lucida.enable = false;
    polkit.enable = true;
    sessions.x11.enable = false;
    aerothemeplasma = {
      enable = true;
      sddm.enable = false;
      plymouth.enable = false;
    };
  };
}
