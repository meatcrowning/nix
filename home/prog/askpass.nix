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

  # App icon: the planetary seal of Saturn (the gatekeeper), redrawn as clean
  # vector SVG in app-icons/. Installed into the hicolor icon theme so the
  # titlebar program-icon slot finds it (hyprvtb resolves class ->
  # .desktop -> Icon= -> icon theme; a currentColor SVG it tints to the title
  # colour) — same pattern as goetia's seal.
  home.file.".local/share/icons/hicolor/scalable/apps/vista-askpass.svg".source = ./app-icons/askpass.svg;
  # …and declare it a SEAL, so the panel paints its currentColor strokes in
  # the focus colour instead of the file's baked fallback (app-icons/seals.nix).
  my.appSeals = [ "vista-askpass" ];

  # NoDisplay desktop entry: the dialog is not a launcher app, but the titlebar
  # resolves the program icon through the freedesktop chain (class ->
  # vista-askpass.desktop -> Icon=), so the seal needs a home here. NoDisplay
  # keeps it out of the runner (Launcher.qml skips a.noDisplay).
  home.file.".local/share/applications/vista-askpass.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=vista-askpass
    Comment=SUDO_ASKPASS password dialog
    Exec=${askpass-dialog}/bin/vista-askpass
    Icon=vista-askpass
    NoDisplay=true
    Terminal=false
    Categories=Utility;
    Keywords=bespoke;sudo;askpass;
  '';

  # SUDO_ASKPASS points at a STABLE path, not at the wrapper's /nix/store path.
  #
  # This is not cosmetic. `SUDO_ASKPASS` used to be the store path, which is a
  # different string in every generation — and a process only reads its
  # environment once. Long-lived shells (this repo's agents run `sudo -A`
  # constantly, and their shells outlive many rebuilds) therefore kept exec'ing
  # the wrapper from whichever generation they were born in, forever. When the
  # dialog was replaced, 31 live processes still held the previous store path
  # and kept popping the OLD ksshaskpass dialog; the user reported "it still
  # looks like the light theme" and they were exactly right. A stable path makes
  # every future shell follow the symlink to the current wrapper instead.
  #
  # It cannot rescue a process that ALREADY holds a store path — nothing can,
  # /nix/store is immutable — so the changeover still costs one new shell. It
  # means there is never a second changeover. It also closes the hazard that a
  # `nix-collect-garbage` deletes the old wrapper out from under those shells
  # and breaks `sudo -A` outright.
  home.file.".local/bin/sudo-askpass".source = "${sudo-askpass}/bin/sudo-askpass";
  home.sessionVariables.SUDO_ASKPASS = "/home/lam/.local/bin/sudo-askpass";

  # ...AND re-export it unconditionally from .zshenv, which is the half that
  # actually rescues the shells that are already running.
  #
  # home.sessionVariables lands in hm-session-vars.sh, and that file guards
  # itself with __HM_SESS_VARS_SOURCED. A long-lived process that sourced it
  # once already has the guard set in its environment, so every shell it spawns
  # inherits the guard, skips the file, and keeps the STALE value — which is how
  # 31 live processes went on invoking the previous generation's wrapper (and
  # therefore ksshaskpass, confirmed in the journal: `ksshaskpass[1762281]:
  # Unable to parse phrase "[sudo] password for lam: "`) long after the dialog
  # was replaced. Waiting for the user to restart every shell is not a fix when
  # agents run `sudo -A` from those shells constantly.
  #
  # zsh sources .zshenv on EVERY invocation, interactive or not, and this export
  # sits outside every guard — so the next command an existing agent session runs
  # already gets the current wrapper. Placed here rather than in zsh.nix so the
  # whole askpass seam stays in one file; home-manager merges the option.
  programs.zsh.envExtra = ''
    # See home/prog/askpass.nix — unconditional on purpose, overrides the stale
    # value a long-lived parent process may have inherited.
    export SUDO_ASKPASS="/home/lam/.local/bin/sudo-askpass"
  '';
}
