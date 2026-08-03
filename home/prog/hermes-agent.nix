{ ... }:

{
  # Hermes Agent (Nous Research) — installed via its own curl|bash installer
  # (~/.hermes), not packaged in nix. The installer tries to append PATH
  # lines to ~/.zshrc, which is a /nix/store symlink here and refuses the
  # write — so the PATH entries it wanted live here instead.
  home.sessionPath = [
    "$HOME/.local/bin"
    "$HOME/.hermes/bin"
  ];

  # home.sessionPath alone lives in hm-session-vars.sh, which self-guards on
  # $__HM_SESS_VARS_SOURCED — a no-op for any shell descended from a process
  # that already sourced an older copy (every terminal in an already-running
  # session). envExtra has no such guard, so it's what actually reaches a
  # freshly opened terminal without a full logout/login.
  programs.zsh.envExtra = ''
    export PATH="$HOME/.local/bin:$HOME/.hermes/bin''${PATH:+:}$PATH"
  '';
}
