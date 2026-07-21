{ pkgs, host, ... }:

{
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;
    #bindkey "''${key[Up]}" up-line-or-search;
    shellAliases =
      # `top` is a full NixOS system, so update/rbsys/rbhome all go through
      # `nixos-rebuild` (passwordless via sys/nixos-rebuild.nix, which only
      # exists on top). `air` is plain Fedora with standalone home-manager —
      # there's no NixOS layer, so these just drive `home-manager switch`
      # against the `air` flake output instead, and `trash` isn't set up
      # passwordless there.
      if host == "top" then {
        update = "sudo nixos-rebuild switch --upgrade --flake /home/lam/nix/#top";
        rbsys = "sudo nixos-rebuild switch --flake /home/lam/nix/#top";
        rbhome = "sudo nixos-rebuild switch --flake /home/lam/nix/#top";
        trash = "sudo nix-collect-garbage";
      } else {
        update = "nix flake update --flake /home/lam/nix && home-manager switch --flake /home/lam/nix#air";
        rbsys = "home-manager switch --flake /home/lam/nix#air";
        rbhome = "home-manager switch --flake /home/lam/nix#air";
        trash = "nix-collect-garbage";
      } // {
        ll = "ls -l";
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
