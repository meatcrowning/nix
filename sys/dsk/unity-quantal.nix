{ pkgs, ... }:
let
  unity = pkgs.callPackage ../../lib/unity-quantal { };
  # Current Rhythmbox stands in for Quantal's 2.97 player: its 2012 media
  # decoders and online plugins would need the isolated-app sandbox.
  rhythmbox = pkgs.symlinkJoin {
    name = "unity-${pkgs.rhythmbox.name}";
    paths = [ pkgs.rhythmbox ];
    postBuild = ''
      for entry in "$out"/share/applications/*.desktop; do
        target=$(readlink "$entry")
        rm "$entry"
        sed '/^\[Desktop Entry\]$/a OnlyShowIn=Unity;' "$target" > "$entry"
      done
    '';
  };
in
{
  # A top-only greeter choice. The shell is the original 6.8 release; Xorg,
  # graphics drivers, application processes, and session management are native.
  services.xserver.enable = true;
  services.displayManager.sessionPackages = [ unity ];
  environment.systemPackages = [ unity rhythmbox ];
  system.build.unityQuantal = unity;
  security.pam.services.cinnamon-screensaver = { };
  programs.dconf.enable = true;

  xdg.portal.config.unity = {
    default = [ "gtk" ];
    "org.freedesktop.impl.portal.FileChooser" = [ "kde" ];
  };
}
