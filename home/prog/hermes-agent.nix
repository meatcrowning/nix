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
}
