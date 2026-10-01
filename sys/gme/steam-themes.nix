{ config, pkgs, user, ... }:

let
  # Use Jovian's source-built package without importing its SteamOS session.
  jovian = builtins.fetchTarball {
    url = "https://github.com/Jovian-Experiments/Jovian-NixOS/archive/49c2c729cc6d78bf64ae252d3a31e6311d896ab9.tar.gz";
    sha256 = "sha256-mpFFy+vabu4WOma4Tx7myAPUaj+Ob58qK8ZXL/xANmo=";
  };
  decky = pkgs.callPackage "${jovian}/pkgs/decky-loader" { };
  cssArchive = pkgs.fetchurl {
    url = "https://cdn.tzatzikiweeb.moe/file/steam-deck-homebrew/versions/1a1e8f4dded8494febe56df16429ef5bba1e5b8feb3fd989d5808fbef0d71350.zip";
    sha256 = "1a1e8f4dded8494febe56df16429ef5bba1e5b8feb3fd989d5808fbef0d71350";
  };
  themeArchive = pkgs.fetchurl {
    url = "https://api.deckthemes.com/blobs/4da0b741-22b1-4df2-905d-f135fffda295";
    hash = "sha256-BPKsuyiLYsv7nFqpDY5+35isRC/WRnurqErrVI/7CnE=";
  };
  seed = pkgs.runCommand "steam-clean-gameview-seed" {
    nativeBuildInputs = [ pkgs.unzip ];
  } ''
    mkdir -p "$out/plugins" "$out/themes"
    unzip -q ${cssArchive} -d "$out/plugins"
    unzip -q ${themeArchive} -d "$out/themes"
    echo '{"active":true}' > "$out/themes/Clean Gameview/config_USER.json"
  '';
  state = "/var/lib/decky-loader";
  userHome = config.users.users.${user}.home;
in
{
  # top only: book has no native Steam client. Mutable copies let the user
  # change theme options or update plugins through Decky's own interface.
  systemd.services.decky-loader = {
    description = "Steam Big Picture themes (Decky Loader)";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" ];
    path = [ pkgs.coreutils pkgs.systemd pkgs.psmisc ];
    environment = {
      UNPRIVILEGED_USER = user;
      UNPRIVILEGED_PATH = state;
      PRIVILEGED_PATH = state;
      SERVER_HOST = "127.0.0.1";
      KEEP_SYSTEMD_SERVICE = "1";
    };
    preStart = ''
      install -d -o ${user} -g users ${state}/{plugins,themes,settings,data,logs}
      if [ ! -e ${state}/plugins/SDH-CssLoader ]; then
        cp -R ${seed}/plugins/SDH-CssLoader ${state}/plugins/
        chmod -R u+w ${state}/plugins/SDH-CssLoader
        chown -R ${user}:users ${state}/plugins/SDH-CssLoader
      fi
      if [ ! -e '${state}/themes/Clean Gameview' ]; then
        cp -R '${seed}/themes/Clean Gameview' ${state}/themes/
        chmod -R u+w '${state}/themes/Clean Gameview'
        chown -R ${user}:users '${state}/themes/Clean Gameview'
      fi
      # Steam reads this on its next launch; never restart the live client.
      install -d -o ${user} -g users '${userHome}/.local/share/Steam'
      touch '${userHome}/.local/share/Steam/.cef-enable-remote-debugging'
      chown ${user}:users '${userHome}/.local/share/Steam/.cef-enable-remote-debugging'
    '';
    serviceConfig = {
      ExecStart = "${decky}/bin/decky-loader";
      StateDirectory = "decky-loader";
      Restart = "on-failure";
      RestartSec = 5;
      TimeoutStopSec = 45;
    };
  };
}
