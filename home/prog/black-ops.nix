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
  dxvkConfig = pkgs.writeText "black-ops-dxvk.conf" ''
    d3d9.maxAvailableMemory = 1024
  '';
  launcher = pkgs.writeShellApplication {
    name = "black-ops";
    runtimeInputs = [ wine pkgs.cabextract pkgs.coreutils pkgs.util-linux ];
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
      case "''${1:-}" in
        --zombies|--multiplayer)
          mode=t5sp
          [[ "$1" != --multiplayer ]] || mode=t5mp
          shift
          # The client writes profiles beside its assets. Copy only the pinned
          # distribution files; preserve the player's generated settings/stats.
          client="''${BLACK_OPS_LAN_DIR:-''${XDG_DATA_HOME:-$HOME/.local/share}/black-ops/plutonium}"
          mkdir -p "$client"
          cp -r --no-preserve=mode ${lanClient}/. "$client/"
          game_windows=$(winepath -w "$game")
          cd "$client"
          exec wine bin/plutonium-bootstrapper-win32.exe "$mode" "$game_windows" -lan +name Player "$@"
          ;;
      esac
      cd "$game"
      exec wine BlackOps.exe "$@"
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
        Actions=Zombies;Multiplayer;

        [Desktop Action Zombies]
        Name=Zombies (Offline)
        Exec=${launcher}/bin/black-ops --zombies

        [Desktop Action Multiplayer]
        Name=Multiplayer Bots (Offline)
        Exec=${launcher}/bin/black-ops --multiplayer
      '';
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
