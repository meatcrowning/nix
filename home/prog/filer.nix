{ config, pkgs, ... }:

# Desktop entry for `filer`, the standalone Qt/QML file browser that was split
# out of the Quickshell panel (lives at ~/Projects/filer). This makes it show up
# in the Quickshell runner, which enumerates XDG desktop entries
# (DesktopEntries.applications in home/prog/quickshell-files/Launcher.qml).
#
# Exec points at the project's dev launcher (run.sh → `nix develop`) rather than
# a store-built binary on purpose: filer is under active development, so this way
# the runner always launches the current working tree without a rebuild. Swap to
# the packaged binary (`nix run /home/lam/Projects/filer`) once it settles.
{
  xdg.desktopEntries.filer = {
    name = "filer";
    genericName = "File Browser";
    comment = "Standalone file browser for the top desktop";
    exec = "/home/lam/Projects/filer/run.sh";
    icon = "system-file-manager";
    terminal = false;
    type = "Application";
    categories = [ "Utility" "System" "FileTools" ];
  };
}
