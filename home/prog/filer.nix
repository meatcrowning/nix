{ ... }:

# Desktop entry for `filer`, the standalone Qt/QML file browser that was split
# out of the Quickshell panel (lives at ~/Projects/filer). This makes it show up
# in the Quickshell runner, which enumerates XDG desktop entries
# (DesktopEntries.applications in home/prog/quickshell-files/Launcher.qml).
#
# Written via home.file rather than xdg.desktopEntries because this config keeps
# xdg.enable = false (so HM doesn't take over the XDG base dirs), and
# xdg.desktopEntries only emits files when xdg.enable is on. home.file links the
# single .desktop alongside the existing real files in ~/.local/share/applications.
#
# Exec points at the project's dev launcher (run.sh → `nix develop`) on purpose:
# filer is under active development, so the runner always launches the current
# working tree without a rebuild. Swap to the packaged binary
# (`nix run /home/lam/Projects/filer`) once it settles.
{
  home.file.".local/share/applications/filer.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=filer
    GenericName=File Browser
    Comment=Standalone file browser for the top desktop
    Exec=/home/lam/Projects/filer/run.sh
    Icon=system-file-manager
    Terminal=false
    Categories=Utility;System;FileTools;
  '';
}
