{ config, pkgs, inputs, user, ... }:

{
  imports = [
    ./home
  ];

  home = {
    username = "${user}";
    homeDirectory = "/home/${user}";
    stateVersion = "25.11";
    enableNixpkgsReleaseCheck = false;
  };
}
