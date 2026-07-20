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
      # Home is managed only through the system rebuild now (the standalone
      # homeConfigurations was removed to kill the dual-wiring clobber), so
      # rbhome just IS rbsys. A NOPASSWD sudo rule (sys/nixos-rebuild.nix) makes
      # all three passwordless.
      rbhome = "sudo nixos-rebuild switch --flake /home/lam/nix/#top";
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
