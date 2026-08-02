{ config, pkgs, ... }:

{
  # Propagates the Settings "pixel font" pick (settings.json fontFamily /
  # fontSize) out to the four surfaces that historically hardcoded the default
  # face: kitty, the hyprvtb titlebar, kdeglobals (KDE/Qt system font) and
  # qutebrowser. The panel and the six Qt apps already read the pick live
  # (Theme.qml / deskstyle.py); this closes the gap for the rest.
  #
  # Invoked three ways:
  #   * wal-set.sh (login + wallpaper change) — the font roles used to be pinned
  #     hardcoded there; now it delegates to this script so the persisted pick
  #     lands on-screen before the first window on login and stays correct
  #     across wallpaper changes.
  #   * The panel's SettingsApply.qml, live, when fontFamily/fontSize change.
  xdg.configFile."scripts/apply-pixel-font.sh" = {
    source = ./pixel-font-files/apply-pixel-font.sh;
    executable = true;
  };
}
