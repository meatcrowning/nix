{ config, pkgs, ... }:

{
  services.udiskie = {
    enable = true;
    notify = false; # mount/unmount toasts are noise
    settings = {
      program_options = {
        file_manager = "${pkgs.kdePackages.dolphin}/bin/dolphin";
      };
    };
  };
}
