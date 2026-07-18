{ pkgs, ... }:

{
  programs.bash = {
    enable = true;
    # If we are in a nix-shell, automatically exec zsh
    initExtra = ''
      if [[ -n "$IN_NIX_SHELL" && "$SHELL" != *"zsh" ]]; then
        exec zsh
      fi
    '';
  };
}
