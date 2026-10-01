{ config, lib, pkgs, user, ... }:

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
  steamGridDbArchive = pkgs.fetchurl {
    url = "https://cdn.tzatzikiweeb.moe/file/steam-deck-homebrew/versions/6d6eca184677dc9ff7736439ee7a575ca8ab386c5ffb1627d446bc43dbd1ecf3.zip";
    sha256 = "6d6eca184677dc9ff7736439ee7a575ca8ab386c5ffb1627d446bc43dbd1ecf3";
  };
  themeArchives = map (theme: pkgs.fetchurl {
    url = "https://api.deckthemes.com/blobs/${theme.id}";
    inherit (theme) hash;
  }) [
    { # Clean Gameview
      id = "4da0b741-22b1-4df2-905d-f135fffda295";
      hash = "sha256-BPKsuyiLYsv7nFqpDY5+35isRC/WRnurqErrVI/7CnE=";
    }
    { # Art Hero
      id = "692d427e-eda3-4a13-ac49-c8ad5455e1b3";
      hash = "sha256-IpJT47R5dUAbIzQlt98unDtHRCHFSU/OdX1V0qSEAec=";
    }
    { # More Library Icons (six columns by default)
      id = "79739a7b-83b9-45de-b0ae-4e290cc59da0";
      hash = "sha256-7FUiiVzFHey1CTR8JKwwr4+zWG7ko8GNZt0yQegVhKw=";
    }
    # Art Hero requires these three themes; Mini Carousel defaults to its
    # requested Size=0.7. Keep the dependency closure pinned with the theme.
    { # Mini Carousel
      id = "4685f114-9ee8-4869-97ce-6f1ae0e351f9";
      hash = "sha256-YRfsF3ZSVQXZsjolSUwYjNK20nwnW47oTBvdzYc/9wU=";
    }
    { # Game Header Text Stroke
      id = "0475e0ef-ec4b-4800-a1d8-d110b159a25d";
      hash = "sha256-++SV2U43AySBuESb/JKpPXcnDf6yLQa5sRpBSrVL4lM=";
    }
    { # Centered Game Text
      id = "8f452b28-e3ce-4314-a08f-68b0a9e8e415";
      hash = "sha256-D//myXIbu+UELekFb436jKvPJ47oxLe22JlhXZU26us=";
    }
  ];
  seed = pkgs.runCommand "steam-big-picture-theme-seed" {
    nativeBuildInputs = [ pkgs.unzip ];
  } ''
    mkdir -p "$out/plugins" "$out/themes"
    unzip -q ${cssArchive} -d "$out/plugins"
    unzip -q ${steamGridDbArchive} -d "$out/plugins"
    ${lib.concatMapStringsSep "\n" (archive: ''unzip -q ${archive} -d "$out/themes"'') themeArchives}
    mkdir -p "$out/migrations"
    cp "$out/themes/More Library Icons/shared.css" "$out/migrations/library-icons-upstream.css"
    cp ${./steam-library-icons.css} "$out/themes/More Library Icons/shared.css"
    for theme in "$out/themes/"*; do
      echo '{"active":true}' > "$theme/config_USER.json"
    done
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
    # Decky's reinjection can restart steamwebhelper. Apply theme-only changes
    # through CSS Loader; pick up service/package changes on the next boot.
    restartIfChanged = false;
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
      for plugin in ${seed}/plugins/*; do
        destination="${state}/plugins/$(basename "$plugin")"
        if [ ! -e "$destination" ]; then
          cp -R "$plugin" "$destination"
          chmod -R u+w "$destination"
          chown -R ${user}:users "$destination"
        fi
      done
      for theme in ${seed}/themes/*; do
        destination="${state}/themes/$(basename "$theme")"
        if [ ! -e "$destination" ]; then
          cp -R "$theme" "$destination"
          chmod -R u+w "$destination"
          chown -R ${user}:users "$destination"
        fi
      done
      # Migrate only the exact upstream file, preserving any user CSS edits.
      if cmp -s '${state}/themes/More Library Icons/shared.css' \
          ${seed}/migrations/library-icons-upstream.css; then
        install -m 644 -o ${user} -g users \
          '${seed}/themes/More Library Icons/shared.css' \
          '${state}/themes/More Library Icons/shared.css'
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
