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
    # palette. NOTE: this is a static snapshot of the palette (orange, as of
    # 2026-07) — ly's config is system-level and can't follow wallpaper
    # changes. Colors are 0xSSRRGGBB (SS = styling; 01 = bold).
    displayManager.ly.settings = {
      animation = "colormix";
      colormix_col1 = "0x00CC4400"; # accent
      colormix_col2 = "0x0054382A"; # dim
      colormix_col3 = "0x20000000"; # near-black (hi-black style)
      fg = "0x00E08E65";            # input text — palette "ok", readable on the waves
      border_fg = "0x00CC4400";     # box border = accent
      error_fg = "0x01FA5C0C";      # bold crit
    };
    desktopManager.plasma6.enable = true;
    # Hyprland is the default session; aerotheme (when enabled) takes over instead.
    # Plasma stays installed and selectable at the greeter — it also supplies
    # dolphin on PATH and xdg-desktop-portal-kde, which the Hyprland setup uses.
    displayManager.defaultSession =
      if config.my.aerotheme.enable then "aerothemeplasma" else "hyprland";
  };

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
