{ config, pkgs, ... }:

{
  services.udiskie = {
    enable = false;
    settings = {
      program_options = {
        file_manager = "${pkgs.kdePackages.dolphin}/bin/dolphin";
      };
    };
  };
}
