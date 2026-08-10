{ config, pkgs, user, ... }:

{
  users.users = {
    ${user} = {
      isNormalUser = true;
      description = "${user}";
      extraGroups = [ "networkmanager" "wheel" "video" ];
      shell = pkgs.zsh;
      # o+x so the DynamicUser ollama service (ProtectHome=read-only,
      # sys/ai/ollama.nix) can traverse into ~/.ollama/models. NixOS's
      # update-users-groups.pl chmods $HOME to homeMode on every switch
      # regardless of createHome, so a one-off `chmod o+x` keeps getting
      # silently reverted by the next rebuild — this is the durable fix.
      homeMode = "751";
    };
    root = {
      shell = pkgs.zsh;
    };
  };

  programs.zsh.enable = true;
}
