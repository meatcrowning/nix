{ pkgs, lib, host, ... }:

let
  theme = pkgs.writeShellScriptBin "ableton-theme" ''
    exec ${pkgs.python3}/bin/python3 ${./ableton-theme.py} "$@"
  '';
  ableton = pkgs.writeShellScriptBin "ableton-live" ''
    set -e
    ${theme}/bin/ableton-theme
    cd "$HOME/.wine/drive_c/ProgramData/Ableton/Live 11 Suite/Program"
    # Keep Live's popups inside Wine rather than letting Compiz place/focus
    # them independently. A named desktop affects only this launch, not the
    # other applications in the shared prefix. Other desktops stay native.
    case ":''${XDG_CURRENT_DESKTOP:-}:" in
      *:Unity:*)
        size="''${ABLETON_DESKTOP_SIZE:-1600x900}"
        if [[ ! "$size" =~ ^[1-9][0-9]{2,3}x[1-9][0-9]{2,3}$ ]]; then
          echo 'ableton-live: ABLETON_DESKTOP_SIZE must be WIDTHxHEIGHT (100–9999 each)' >&2
          exit 1
        fi
        exec ${pkgs.wineWow64Packages.staging}/bin/wine explorer "/desktop=Ableton,$size" \
          "Ableton Live 11 Suite.exe" "$@"
        ;;
    esac
    exec ${pkgs.wineWow64Packages.staging}/bin/wine "Ableton Live 11 Suite.exe" "$@"
  '';
in
lib.mkIf (host == "top") {
  home.packages = [ ableton theme ];

  # This desktop-file ID is the one Wine generated under wine/Programs/. A
  # root-level file with the same ID wins, so KDE keeps one Ableton result and
  # the existing Wine menu entry points at this working launcher too.
  home.file.".local/share/applications/wine-Programs-Ableton Live 11 Suite.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Ableton Live 11 Suite
    Comment=Digital audio workstation
    Exec=${ableton}/bin/ableton-live %F
    TryExec=/home/lam/.wine/drive_c/ProgramData/Ableton/Live 11 Suite/Program/Ableton Live 11 Suite.exe
    Icon=3CC9_Ableton Live 11 Suite.0
    Terminal=false
    StartupNotify=true
    StartupWMClass=ableton live 11 suite.exe
    Categories=AudioVideo;Audio;Music;
  '';
}
