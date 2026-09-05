{ pkgs, ... }:

let
  theme = pkgs.writeShellScriptBin "ableton-theme" ''
    exec ${pkgs.python3}/bin/python3 ${./ableton-theme.py} "$@"
  '';
  ableton = pkgs.writeShellScriptBin "ableton-live" ''
    set -e
    ${theme}/bin/ableton-theme
    cd "$HOME/.wine/drive_c/ProgramData/Ableton/Live 11 Suite/Program"
    exec ${pkgs.wineWow64Packages.staging}/bin/wine "Ableton Live 11 Suite.exe" "$@"
  '';
in
{
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
