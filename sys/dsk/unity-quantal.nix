{ pkgs, ... }:
let
  unity = pkgs.callPackage ../../lib/unity-quantal {
    musicLibrary = "/run/media/lam/SSD/aud";
  };
in
{
  # A top-only greeter choice. The shell is the original 6.8 release; Xorg,
  # graphics drivers, application processes, and session management are native.
  services.xserver.enable = true;
  services.displayManager.sessionPackages = [ unity ];
  environment.systemPackages = [ unity ];
  fonts.packages = [ unity.fonts ];
  system.build.unityQuantal = unity;
  security.pam.services.cinnamon-screensaver = { };
  programs.dconf.enable = true;

  xdg.portal.config.unity = {
    default = [ "gtk" ];
    "org.freedesktop.impl.portal.FileChooser" = [ "kde" ];
  };
}
