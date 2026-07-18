{ config, pkgs, ... }:

{
  xdg.configFile = {
    "qutebrowser/autoconfig.yml" = {
      source = ./qutebrowser-files/autoconfig.yml;
      force = true; # user chose to overwrite their existing autoconfig.yml with this
    };
    "qutebrowser/quickmarks".source = ./qutebrowser-files/quickmarks;
    "qutebrowser/bookmarks/urls".source = ./qutebrowser-files/bookmarks/urls;
  };
}
