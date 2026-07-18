{ config, pkgs, ... }:

{
  programs.mpv = {
    enable = true;
    config = {
      loop-file = "inf";
    };
  };
}
