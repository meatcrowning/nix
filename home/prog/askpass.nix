{ pkgs, lib, host, ... }:

# The `SUDO_ASKPASS` password dialog — full Vista-UAC treatment: the chime plays
# as the dialog appears, and the `askpass-dim` window rule in hyprland.lua
# dims/centres/pins it while the panel dims its own bar (Askpass.qml). The
# password goes straight from the dialog's stdout into sudo's pipe — never a
# command line, a file, a shell variable, or a log.
#
# The dialog itself is `apps/askpass` (Qt/QML, live source, same pattern as the
# other vendored apps). It replaced ksshaskpass, which drew a stock Plasma
# dialog and therefore inherited whatever KDE colour scheme the machine had:
# acceptable on top, LIGHT-THEMED on book, which has no Plasma theme of ours.
# The replacement paints every pixel from the wal palette, so both hosts match
# and nothing depends on Plasma being installed.
#
# ksshaskpass is STILL INSTALLED, deliberately, as the fallback below.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  # air: nixpkgs' Qt can't create a GPU context on Apple Silicon, so exec the
  # SYSTEM python3 with Fedora's python3-pyside6 — same split as filer/viewer.
  askpass-dialog =
    if host == "air" then
      pkgs.writeShellScriptBin "vista-askpass" ''
        exec /usr/bin/python3 /home/lam/nix/apps/askpass/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "vista-askpass";
        version = "live";
        dontUnpack = true;
        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative ];
        dontWrapQtApps = true;
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/vista-askpass \
            --add-flags /home/lam/nix/apps/askpass/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };

  # `sudo -A` is load-bearing here (agents run every root command through it, in
  # contexts with no tty), so the wrapper must never be able to leave the
  # machine unable to authenticate. Hence the exit-code contract:
  #
  #   0  password on stdout        -> pass it through
  #   1  user cancelled            -> pass it through. NOT a failure.
  #   3  dialog could not be shown -> fall back to ksshaskpass
  #   *  anything else (127 etc.)  -> fall back to ksshaskpass
  #
  # The dialog is exec'd with stdout inherited from sudo's pipe: the password is
  # never captured into a shell variable, so it cannot leak via `set -x`, a
  # trap, or the process's environment.
  sudo-askpass = pkgs.writeShellScriptBin "sudo-askpass" ''
    ${pkgs.pipewire}/bin/pw-play "$HOME/.local/share/sounds/vista/Windows User Account Control.wav" 2>/dev/null &

    ${askpass-dialog}/bin/vista-askpass "$@"
    rc=$?
    case "$rc" in
      0|1) exit "$rc" ;;
    esac
    echo "sudo-askpass: dialog exited $rc, falling back to ksshaskpass" >&2
    exec ${pkgs.kdePackages.ksshaskpass}/bin/ksshaskpass "$@"
  '';
in
{
  # Lets non-TTY contexts (Claude Code sessions, scripts) run root commands
  # via `sudo -A <cmd>`.
  home.packages = [ sudo-askpass askpass-dialog pkgs.kdePackages.ksshaskpass ];
  home.sessionVariables.SUDO_ASKPASS = "${sudo-askpass}/bin/sudo-askpass";
}
