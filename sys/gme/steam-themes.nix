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
  audioArchive = pkgs.fetchurl {
    url = "https://cdn.tzatzikiweeb.moe/file/steam-deck-homebrew/versions/fd5a090c2e2cd4da6723d7bd08937ab31b9f8d4663510431713da531343e303f.zip";
    sha256 = "fd5a090c2e2cd4da6723d7bd08937ab31b9f8d4663510431713da531343e303f";
  };
  audioPlugin = pkgs.runCommand "steam-audio-loader" {
    nativeBuildInputs = [ pkgs.unzip pkgs.python3 ];
  } ''
    unzip -q ${audioArchive}
    mv SDH-AudioLoader "$out"
    chmod -R u+w "$out"
    python3 ${./steam-audio/patch.py} "$out/dist/index.js" ${./steam-audio/bridge.js}
  '';
  audioPacks = map (pack: pkgs.fetchurl {
    url = "https://api.deckthemes.com/blobs/${pack.id}";
    inherit (pack) hash;
  }) [
    { # Nintendo GameCube Menu SFX
      id = "dc05a069-161e-483d-aaeb-627c37a3c865";
      hash = "sha256-6CaWnSrwITiqnnrj5B1RUn4AICBXGfv0KvnFQGEZhmA=";
    }
    { # Kingdom Hearts Menu
      id = "f8c3d003-0106-4691-84b1-30b546c071ca";
      hash = "sha256-HlNroYeTbx94rPArscXaI2GMsjHmkd/2gzkwX6ibbY8=";
    }
    { # NFS Underground PS2 Beta UI sounds
      id = "692ba5df-b978-44ee-bb8f-139f1bdde158";
      hash = "sha256-jiyssSJll/eBncitSAeiTFzoxmFQESTxqi6XXVFzY5M=";
    }
    { # Metal Gear Solid SFX Pack for AudioLoader
      id = "62332540-4629-4e30-903d-0943b699335f";
      hash = "sha256-xYja6pCcSONJ4A5OU3YaZ9EJ9viBHZSAgXblZt4A7SM=";
    }
    { # Xbox 360 Metro UI Sounds
      id = "25296c42-7750-463a-af4a-68fa31aaae0b";
      hash = "sha256-bmu8tA+aJ8P5xDvCWIuKuzGTFSB1FwgnBYsNUgWvn2g=";
    }
    { # PS2 Ambience
      id = "85cdba2c-e85b-49d1-b38d-01556962768f";
      hash = "sha256-10KTFIOmK9d9G1o87GkHnwq2VtGQyn35w2LlSdIp0Ho=";
    }
  ];
  deckyUi = pkgs.fetchurl {
    url = "https://registry.npmjs.org/@decky/ui/-/ui-4.12.1.tgz";
    hash = "sha256-G6HEPZPN+DrdiCr+DdYsewF0aBl+AGVkq2XAvz43eN4=";
  };
  deckyApi = pkgs.fetchurl {
    url = "https://registry.npmjs.org/@decky/api/-/api-1.1.3.tgz";
    hash = "sha256-JzInzYAQT9WpMHMot5jCmauqF0ER42gIEo5hb9q+uAc=";
  };
  homeGrid = pkgs.runCommand "steam-home-library-grid" {
    nativeBuildInputs = [ pkgs.esbuild ];
  } ''
    cp -R ${./steam-home-grid} source
    mkdir -p node_modules/@decky/{ui,api} "$out/dist"
    tar xf ${deckyUi} -C node_modules/@decky/ui --strip-components=1
    tar xf ${deckyApi} -C node_modules/@decky/api --strip-components=1
    esbuild source/index.jsx --bundle --format=esm --target=chrome110 \
      --alias:react=./source/react-shim.js \
      --alias:@decky/manifest=./source/plugin.json --loader:.css=text --loader:.svg=dataurl \
      --outfile="$out/dist/index.js"
    cp source/{plugin,package}.json source/main.py "$out/"
    cp node_modules/@decky/ui/LICENSE "$out/LICENSE.decky-ui"
  '';
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
    mkdir -p "$out/plugins" "$out/themes" "$out/sounds"
    unzip -q ${cssArchive} -d "$out/plugins"
    cp -R ${audioPlugin} "$out/plugins/SDH-AudioLoader"
    ${lib.concatMapStringsSep "\n" (archive: ''unzip -q ${archive} -d "$out/sounds"'') audioPacks}
    unzip -q ${steamGridDbArchive} -d "$out/plugins"
    cp -R ${homeGrid} "$out/plugins/home-library-grid"
    cp -R ${./steam-oled} "$out/themes/OLED Black"
    chmod -R u+w "$out/themes/OLED Black"
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
      install -d -o ${user} -g users ${state}/{plugins,themes,sounds,settings,data,logs}
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
      for pack in ${seed}/sounds/*; do
        destination="${state}/sounds/$(basename "$pack")"
        if [ ! -e "$destination" ]; then
          cp -R "$pack" "$destination"
          chmod -R u+w "$destination"
          chown -R ${user}:users "$destination"
        fi
      done
      # Pin the Home audio integration; user pack selections remain mutable.
      cp -R ${audioPlugin}/. '${state}/plugins/SDH-AudioLoader/'
      chmod -R u+w '${state}/plugins/SDH-AudioLoader'
      chown -R ${user}:users '${state}/plugins/SDH-AudioLoader'
      # This local plugin is declarative; unlike downloaded plugins, update it
      # on every boot. Live updates use Decky's plugin import, never a restart.
      cp -R ${homeGrid}/. '${state}/plugins/home-library-grid/'
      chmod -R u+w '${state}/plugins/home-library-grid'
      chown -R ${user}:users '${state}/plugins/home-library-grid'
      cp ${./steam-oled/shared.css} '${state}/themes/OLED Black/shared.css'
      chown ${user}:users '${state}/themes/OLED Black/shared.css'
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
