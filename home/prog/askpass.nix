{ pkgs, ... }:

let
  # GUI sudo password prompt with the full Vista-UAC treatment: the chime
  # plays as the dialog appears, and the askpass-dim window rule in
  # hyprland.lua dims/centres/pins the dialog compositor-side. The password
  # itself goes straight from the dialog to sudo — it never appears in a
  # command line, transcript, or file.
  sudo-askpass = pkgs.writeShellScriptBin "sudo-askpass" ''
    ${pkgs.pipewire}/bin/pw-play "$HOME/.local/share/sounds/vista/Windows User Account Control.wav" 2>/dev/null &
    exec ${pkgs.kdePackages.ksshaskpass}/bin/ksshaskpass "$@"
  '';
in
{
  # Lets non-TTY contexts (Claude Code sessions, scripts) run root commands
  # via `sudo -A <cmd>`.
  home.packages = [ sudo-askpass pkgs.kdePackages.ksshaskpass ];
  home.sessionVariables.SUDO_ASKPASS = "${sudo-askpass}/bin/sudo-askpass";
}
