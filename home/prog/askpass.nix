{ pkgs, ... }:

{
  # GUI sudo password prompt: lets non-TTY contexts (Claude Code sessions,
  # scripts) run root commands via `sudo -A <cmd>` — sudo execs ksshaskpass,
  # which pops a Qt password dialog on the current session and hands the
  # password straight to sudo on stdout. The password never appears in a
  # command line, transcript, or file. SUDO_ASKPASS makes `sudo -A` (and
  # plain `sudo` with no TTY in newer sudos) find it.
  home.packages = [ pkgs.kdePackages.ksshaskpass ];
  home.sessionVariables.SUDO_ASKPASS = "${pkgs.kdePackages.ksshaskpass}/bin/ksshaskpass";
}
