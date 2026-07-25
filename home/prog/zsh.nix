{ pkgs, host, ... }:

{
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;
    #bindkey "''${key[Up]}" up-line-or-search;
    shellAliases =
      # `top` is a full NixOS system, so update/rbsys/rbhome all go through the
      # `rebuild-top` wrapper (passwordless via sys/nixos-rebuild.nix, which only
      # exists on top — it hardcodes `switch --flake /home/lam/nix#top`, so no
      # NOPASSWD-on-arbitrary-flake escalation). `air` is plain Fedora with
      # standalone home-manager — there's no NixOS layer, so these just drive
      # `home-manager switch` against the `air` flake output instead, and `trash`
      # isn't set up passwordless there.
      #
      # The parens around the conditional are load-bearing: an `if/then/else`
      # extends as far right as it can, so `if … then {A} else {B} // {C}`
      # parses as `else ({B} // {C})` — the shared aliases silently applied to
      # `air` only, and `ll`/`tree` did not exist on `top` at all.
      (if host == "top" then {
        update = "sudo rebuild-top --upgrade";
        rbsys = "sudo rebuild-top";
        rbhome = "sudo rebuild-top";
        trash = "sudo nix-collect-garbage";
      } else {
        update = "nix flake update --flake /home/lam/nix && home-manager switch --flake /home/lam/nix#air";
        rbsys = "home-manager switch --flake /home/lam/nix#air";
        rbhome = "home-manager switch --flake /home/lam/nix#air";
        trash = "nix-collect-garbage";
      }) // {
        ll = "ls -l";
        tree = "tree --dirsfirst";
        # Background agent sessions branch into ~/nix/.claude/worktrees/<name>
        # and never clean up, so full copies of the tree accumulate (and make
        # every `grep -r` here return each hit three times). This removes only
        # the ones that are clean AND fully landed on origin/main; see the
        # script header. `wtprune --dry-run` to look first.
        wtprune = "/home/lam/nix/tools/prune-worktrees.sh";
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
