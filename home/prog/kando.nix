{ pkgs, lib, host, ... }:

# Kando pie menu, book only for now (top later).
#
# The app is the Flathub build (menu.kando.Kando, system install) rather than
# nixpkgs' kando: book has no /run/opengl-driver, so a nix Electron gets no
# GPU. Install once with `flatpak install --system flathub menu.kando.Kando`.
#
# Kando 3 on Plasma Wayland needs kando-menu/kwin-integration, a binary KWin
# effect that must match Fedora's libkwin exactly. The upstream prebuilt for
# fedora-44 / kwin 6.7.5 / arm64 is linked into the user plugin dir that
# kwin-momentum.nix already puts on QT_PLUGIN_PATH. After a dnf KWin update,
# bump this to the matching release asset. KWin loads it at the next login.
let
  kwinIntegration = pkgs.fetchzip {
    url = "https://github.com/kando-menu/kwin-integration/releases/download/v0.4.1/fedora-44-kwin-6.7.5-arm64.zip";
    hash = "sha256-kmed9xFrHbycJgVjGl9yUsoFdugxWx31N1qyM+GNaW8=";
    stripRoot = false;
  };
in
lib.mkIf (host == "air") {
  home.file.".local/lib64/qt6/plugins/kwin/effects/plugins/kandointegration.so".source =
    "${kwinIntegration}/kandointegration.so";

  xdg.configFile."autostart/kando.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Kando
    Exec=flatpak run menu.kando.Kando
    Icon=menu.kando.Kando
    X-KDE-autostart-phase=2
  '';

  # Kando registers its menus through the GlobalShortcuts portal, which lands
  # them in kglobalaccel unbound; this applies the menu's own Ctrl+Space.
  programs.plasma.shortcuts."menu.kando.Kando"."example-menu" = "Ctrl+Space";
}
