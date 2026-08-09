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
    # Hyprland is the default session; aerotheme (when enabled) takes over instead.
    # Plasma stays installed and selectable at the greeter — it also supplies
    # dolphin on PATH and xdg-desktop-portal-kde, which the Hyprland setup uses.
    displayManager.defaultSession =
      if config.my.aerotheme.enable then "aerothemeplasma" else "hyprland";
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
  system.activationScripts.lyRuntimeConfig = lib.stringAfter [ "etc" ] ''
    [ -f /etc/ly/config.ini ] || exit 0
    mkdir -p /var/lib/ly
    chown lam:users /var/lib/ly
    cp -f /etc/ly/config.ini /var/lib/ly/config.ini.new
    if [ -f /var/lib/ly/config.ini ]; then
      for k in border_fg colormix_col1 colormix_col2 colormix_col3 error_fg fg; do
        v="$(sed -n "s/^$k=//p" /var/lib/ly/config.ini | head -n1)"
        [ -n "$v" ] && sed -i "s|^$k=.*|$k=$v|" /var/lib/ly/config.ini.new
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

  programs.aeroshell = lib.mkIf config.my.aerotheme.enable {
    enable = true;
    fonts.segoe.enable = true;
    fonts.lucida.enable = false;
    polkit.enable = true;
    aerothemeplasma = {
      enable = true;
      sddm.enable = true;
      plymouth.enable = false;
    };
  };
}
