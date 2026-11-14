{ pkgs, lib, host, ... }:

let
  # An unwrapped Konsole silently falls back to Qt's flat style when the
  # session's plugin path lacks Oxygen, so the wrapper names it.
  konsoleOxygen = pkgs.symlinkJoin {
    name = "konsole-oxygen";
    paths = [ pkgs.kdePackages.konsole ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = ''
      wrapProgram "$out/bin/konsole" \
        --prefix QT_PLUGIN_PATH : ${pkgs.kdePackages.oxygen}/lib/qt-6/plugins \
        --prefix XDG_DATA_DIRS : ${pkgs.kdePackages.oxygen}/share:${pkgs.kdePackages.plasma-integration}/share \
        --set QT_QPA_PLATFORMTHEME kde \
        --set QT_STYLE_OVERRIDE oxygen
    '';
  };
in {
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
    # The Dynamic scheme renders the KStyle-painted window field beneath the
    # terminal text. Keep Konsole managed on both hosts so that scheme and its
    # deliberate chrome defaults are the same everywhere.
    konsoleOxygen
    qttools
    elisa
    # These are the actual applications named by Plasma's default-handler
    # table in home/prog/mime-defaults.nix. On top Plasma brings many of them
    # in transitively; declaring them keeps book's standalone system complete
    # too.
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
    kcolorpicker
   # plasma-framework
    ]) ++ lib.optionals (host == "top") [
    # Top only: kdenlive pulls the separate ffmpeg-full closure.
    kdePackages.kdenlive
    # breeze-square-overlay patches this locally, so there's no cache hit —
    # it always compiles from source (KDE Frameworks/Qt, genuinely slow).
    # Skipped on air for now to keep first bring-up fast; corners just stay
    # round there until this is added back.
    kdePackages.breeze
    ];
}
