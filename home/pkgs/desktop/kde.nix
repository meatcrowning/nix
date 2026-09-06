{ pkgs, lib, host, ... }:

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
    # The menu bar's Finder-shaped desktop menus need a dialog for the two
    # entries that ask something before acting: "Empty Trash…" (a confirm it
    # would otherwise not have, for an irreversible one-click action) and
    # "Go to Folder…" (a directory picker). home/prog/plasma-menubar.nix.
    kdialog
    kate
    kdenlive
    qttools
    elisa
    # These are the actual applications named by Plasma's default-handler
    # table in home/prog/mime-defaults.nix. On top Plasma brings many of them
    # in transitively; declaring them here keeps air's independently managed
    # profile complete too, rather than relying on whatever Fedora happened to
    # have installed at the time of the visual migration.
    dolphin
    gwenview
    haruna
    okular
    qtsvg
    qtstyleplugin-kvantum
    plasmatube
    oxygen
    oxygen-icons
    oxygen-sounds
    partitionmanager
    qtwebsockets
   # plasma-framework
    ]) ++ lib.optionals (host == "top") [
    # breeze-square-overlay patches this locally, so there's no cache hit —
    # it always compiles from source (KDE Frameworks/Qt, genuinely slow).
    # Skipped on air for now to keep first bring-up fast; corners just stay
    # round there until this is added back.
    kdePackages.breeze
    ];
}
