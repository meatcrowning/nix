{ pkgs, ... }:

{
  home.packages = with pkgs; [
    qt6.qtdeclarative
    # kdePackages.polkit-kde-agent-1's actual binary lives at
    # libexec/polkit-kde-authentication-agent-1, which never lands on PATH —
    # normal for polkit agents, but hyprland.lua's autostart (hl.exec_cmd)
    # needs a plain command name. Stable wrapper so that keeps working
    # across package updates (the libexec path's store hash changes).
    (writeShellScriptBin "polkit-kde-agent-1"
      "exec ${kdePackages.polkit-kde-agent-1}/libexec/polkit-kde-authentication-agent-1")
  ] ++ (with kdePackages; [
    kdeconnect-kde
    kcolorchooser
    kate
    kdenlive
    qttools
    elisa
    qtsvg
    breeze
    qtstyleplugin-kvantum
    plasmatube
    oxygen
    oxygen-icons
    oxygen-sounds
    partitionmanager
    qtwebsockets
   # plasma-framework
    ]);
}
