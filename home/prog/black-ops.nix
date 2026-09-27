{ config, host, lib, pkgs, ... }:

let
  wine = pkgs.wineWow64Packages.stable;
  # T5 client files from Plutonium's official updater manifest. Content-addressed
  # downloads keep the tested LAN client stable without storing binaries here.
  lanManifest = builtins.fromJSON (builtins.readFile ./black-ops-lan.json);
  lanClient = pkgs.runCommand "black-ops-lan-r${toString lanManifest.revision}" { } (
    lib.concatMapStringsSep "\n" (file:
      "install -Dm644 ${pkgs.fetchurl { inherit (file) url hash; }} $out/${lib.escapeShellArg file.name}"
    ) lanManifest.files
  );
  botWarfareArchive = pkgs.fetchurl {
    url = "https://github.com/ineedbots/t5_bot_warfare/releases/download/v1.1.1/bo1bw111.zip";
    hash = "sha256-C+9oqXn8Vg7+myytU2H24jliEgz79X0J/i9+/f8dw8M=";
  };
  botWarfare = pkgs.runCommand "black-ops-bot-warfare-1.1.1" {
    nativeBuildInputs = [ pkgs.unzip ];
  } ''
    unzip -q ${botWarfareArchive}
    mkdir -p "$out"
    cp -r "Move to root of Black Ops folder/mods/mp_bots/." "$out/"
  '';
  dxvkConfig = pkgs.writeText "black-ops-dxvk.conf" ''
    d3d9.maxAvailableMemory = 1024
  '';
  launcher = pkgs.writeShellApplication {
    name = "black-ops";
    runtimeInputs = [ wine pkgs.cabextract pkgs.coreutils pkgs.gnused pkgs.util-linux pkgs.python3 ];
    text = ''
      game="''${BLACK_OPS_GAME_DIR:-$HOME/.wine/drive_c/Program Files (x86)/Activision/Call of Duty - Black Ops}"
      if [[ ! -f "$game/BlackOps.exe" ]]; then
        echo "Black Ops installation not found: $game" >&2
        exit 1
      fi
      # Keep Wine upgrades and DLL overrides away from the shared app prefix.
      export WINEPREFIX="''${BLACK_OPS_PREFIX:-''${XDG_DATA_HOME:-$HOME/.local/share}/wineprefixes/black-ops}"
      mkdir -p "$WINEPREFIX"
      exec 9>"$WINEPREFIX/.launcher.lock"
      flock -n 9 || exit 0
      logdir="''${XDG_STATE_HOME:-$HOME/.local/state}/black-ops"
      mkdir -p "$logdir"
      exec >"$logdir/last.log" 2>&1
      export WINEDEBUG="''${WINEDEBUG:--all}"
      export WINEDLLOVERRIDES="winemenubuilder.exe,mscoree,mshtml=d;d3d9=n;xaudio2_7=n,b"
      export DXVK_CONFIG_FILE=${dxvkConfig}
      export DXVK_LOG_PATH="$logdir"
      if [[ ! -f "$WINEPREFIX/.black-ops-runtime-v1" ]]; then
        wineboot --init
        # The builtin audio runtime crashes during Black Ops initialization.
        # Use the redistributable shipped with the game, never a downloaded DLL.
        cabextract -q -L -F XAudio2_7.dll -d "$WINEPREFIX/drive_c/windows/syswow64" \
          "$game/Redist/DirectX/Jun2010_XAudio_x86.cab"
        touch "$WINEPREFIX/.black-ops-runtime-v1"
      fi
      cp -f ${pkgs.dxvk.bin}/x32/d3d9.dll "$WINEPREFIX/drive_c/windows/syswow64/d3d9.dll"
      if [[ ! -f "$WINEPREFIX/.black-ops-controller-v1" ]]; then
        # SDL maps DualSense to XInput; the raw HID backend exposes only DInput.
        wine reg add 'HKLM\System\CurrentControlSet\Services\winebus' \
          /v 'Enable SDL' /t REG_DWORD /d 1 /f
        wine reg add 'HKLM\System\CurrentControlSet\Services\winebus' \
          /v DisableHidraw /t REG_DWORD /d 1 /f
        wineserver -w
        touch "$WINEPREFIX/.black-ops-controller-v1"
      fi
      enable_controller() {
        local cfg="$1"
        mkdir -p "$(dirname "$cfg")"
        if [[ -f "$cfg" ]]; then
          sed -i '/^[[:space:]]*seta\? gpad_enabled /d' "$cfg"
        fi
        echo 'seta gpad_enabled "1"' >> "$cfg"
      }
      case "''${1:-}" in
        --campaign)
          shift
          ;;
        --zombies|--multiplayer|--multiplayer-stock)
          variant="$1"
          mode=t5sp
          [[ "$variant" == --zombies ]] || mode=t5mp
          shift
          # The client writes profiles beside its assets. Copy only the pinned
          # distribution files; preserve the player's generated settings/stats.
          client="''${BLACK_OPS_LAN_DIR:-''${XDG_DATA_HOME:-$HOME/.local/share}/black-ops/plutonium}"
          mkdir -p "$client"
          cp -r --no-preserve=mode ${lanClient}/. "$client/"
          extra=()
          mp_config="$client/storage/t5/players/config_mp.cfg"
          if [[ "$variant" == --multiplayer ]]; then
            mkdir -p "$client/storage/t5/mods/mp_bots" "$client/storage/t5/players/mods/mp_bots"
            cp -r --no-preserve=mode ${botWarfare}/. "$client/storage/t5/mods/mp_bots/"
            # Mods have independent stats/configs. Seed preferences, not ranks.
            mod_config="$client/storage/t5/players/mods/mp_bots/config_mp.cfg"
            if [[ ! -f "$mod_config" && -f "$mp_config" ]]; then
              cp "$mp_config" "$mod_config"
            fi
            mp_config="$mod_config"
            extra+=(+set fs_game mods/mp_bots)
          elif [[ "$variant" == --multiplayer-stock ]]; then
            extra+=(+set fs_game "")
          fi
          if [[ "$mode" == t5sp ]]; then
            enable_controller "$client/storage/t5/players/config.cfg"
          else
            enable_controller "$mp_config"
          fi
          if [[ "$mode" == t5mp && -f "$client/storage/t5/players/config.cfg" ]]; then
            # MP clears action binds on startup/shutdown in this installation.
            # Keep Zombies as the shared-controls source; apply one frame late.
            {
              echo 'wait 1'
              if [[ -f "$mp_config" ]]; then
                sed -n '/^bind[[:alnum:]_]*[[:space:]]/p' "$mp_config"
              fi
              # Retain MP's pause command and omit SP-only save/load controls.
              sed -n '/^bind[[:alnum:]_]*[[:space:]]/ { /savegame\|loadgame/d; /^bind PAUSE /d; p; }' \
                "$client/storage/t5/players/config.cfg"
            } > "$client/storage/t5/black-ops-bindings.cfg"
            extra+=(+exec black-ops-bindings.cfg)
          fi
          game_windows=$(winepath -w "$game")
          cd "$client"
          exec wine bin/plutonium-bootstrapper-win32.exe "$mode" "$game_windows" -lan +name Player "''${extra[@]}" +set gpad_enabled 1 "$@"
          ;;
      esac
      # DLC updates target the LAN client, not the original campaign executable.
      # Reuse the verified pre-update assets without changing the LAN files.
      enable_controller "$game/players/config.cfg"
      campaign=$(python3 ${./black-ops-campaign.py} "$game" "$logdir/dlc-backups" \
        "''${XDG_DATA_HOME:-$HOME/.local/share}/black-ops/campaign")
      cd "$campaign"
      exec wine BlackOps.exe +set gpad_enabled 1 "$@"
    '';
  };
in
{
  config = lib.mkIf (host == "top") {
    home.packages = [ launcher ];

    # Replace Wine's actual file: a flattened duplicate has the same desktop ID,
    # but KDE can still resolve that ID to the original nested Wine shortcut.
    home.file.".local/share/applications/wine/Programs/Activision/Call of Duty - Black Ops/Call of Duty - Black Ops.desktop" = {
      force = true;
      text = ''
        [Desktop Entry]
        Type=Application
        Name=Call of Duty - Black Ops
        Exec=${launcher}/bin/black-ops
        TryExec=${launcher}/bin/black-ops
        Path=${config.home.homeDirectory}/.wine/drive_c/Program Files (x86)/Activision/Call of Duty - Black Ops
        Icon=6C6C_BlackOps.0
        Terminal=false
        StartupNotify=true
        StartupWMClass=blackops.exe
        Categories=Game;
        Actions=Campaign;Zombies;Multiplayer;

        [Desktop Action Campaign]
        Name=Single-player Campaign
        Exec=${launcher}/bin/black-ops --campaign

        [Desktop Action Zombies]
        Name=Zombies (Offline)
        Exec=${launcher}/bin/black-ops --zombies

        [Desktop Action Multiplayer]
        Name=Multiplayer Bots (Offline)
        Exec=${launcher}/bin/black-ops --multiplayer
      '';
    };
    xdg.desktopEntries.black-ops-campaign = {
      name = "Black Ops Campaign";
      exec = "${launcher}/bin/black-ops --campaign";
      icon = "6C6C_BlackOps.0";
      categories = [ "Game" ];
      terminal = false;
    };
    xdg.desktopEntries.black-ops-zombies = {
      name = "Black Ops Zombies (Offline)";
      exec = "${launcher}/bin/black-ops --zombies";
      icon = "6C6C_BlackOps.0";
      categories = [ "Game" ];
      terminal = false;
    };
    xdg.desktopEntries.black-ops-multiplayer = {
      name = "Black Ops Multiplayer Bots (Offline)";
      exec = "${launcher}/bin/black-ops --multiplayer";
      icon = "6C6C_BlackOps.0";
      categories = [ "Game" ];
      terminal = false;
    };
  };
}
