{ pkgs, ... }:

{
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;
    #bindkey "''${key[Up]}" up-line-or-search;
    shellAliases = {
      ll = "ls -l";
      update = "sudo nixos-rebuild switch --upgrade --flake /home/lam/nix/#top";
      rbsys = "sudo nixos-rebuild switch --flake /home/lam/nix/#top";
      rbhome = "home-manager switch --flake /home/lam/nix/#lam";
      trash = "sudo nix-collect-garbage";
      tree = "tree --dirsfirst";
    };
    initContent = ''
      # Set your default prompt
      PROMPT="%1~;"

      # Detect if we are in a nix-shell and override the prompt
      if [[ -n "$IN_NIX_SHELL" ]]; then
        # Using $'\n...' for a literal newline
        PROMPT=$'\n%F{green}%B[yippe!l:%~]%# %f%b '
      fi
    '';
  };
}
