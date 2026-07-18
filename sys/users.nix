{ config, pkgs, user, ... }:

{
  users.users = {
    ${user} = {
      isNormalUser = true;
      description = "${user}";
      extraGroups = [ "networkmanager" "wheel" "video" ];
      shell = pkgs.zsh;
    };
    root = {
      shell = pkgs.zsh;
    };
  };

  programs.zsh.enable = true;
}
