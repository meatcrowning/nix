{ config, pkgs, ... }:

{
  xdg.configFile = {
    "qutebrowser/autoconfig.yml" = {
      source = ./qutebrowser-files/autoconfig.yml;
      force = true; # user chose to overwrite their existing autoconfig.yml with this
    };
    # Read at every qutebrowser start; loads autoconfig.yml then overrides the
    # font keys from the desktop's settings.json pick (see the file header).
    # autoconfig.yml alone cannot do this: it is a force-deployed store file.
    "qutebrowser/config.py".source = ./qutebrowser-files/config.py;
    "qutebrowser/quickmarks".source = ./qutebrowser-files/quickmarks;
    "qutebrowser/bookmarks/urls".source = ./qutebrowser-files/bookmarks/urls;
  };
}
