{ config, host, lib, pkgs, ... }:

let
  wine = pkgs.wineWow64Packages.stable;
  client = pkgs.fetchurl {
    name = "iw4x.dll";
    url = "https://github.com/iw4x/iw4x-client/releases/download/r5149/iw4x.dll";
    hash = "sha256-dwlv0wwzcvt/+OF1cMelVGGtBsmgE3SSb6hUn92odJQ=";
  };
  rawArchive = pkgs.fetchurl {
    name = "iw4x-rawfiles.zip";
    url = "https://github.com/iw4x/iw4x-rawfiles/releases/download/v0.2.36/release.zip";
    hash = "sha256-HoBCDAI5focuAlgdOgg7MduZxEOoRJJnyKIQi/9uImA=";
  };
  botArchive = pkgs.fetchurl {
    name = "iw4bw230.zip";
    url = "https://github.com/ineedbots/iw4_bot_warfare/releases/download/v2.3.0/iw4bw230.zip";
    hash = "sha256-ashwiJOsGNLz/ZbUnZXWE1RJpQpAmBEXLvKzj6lO2tw=";
  };
  rawFiles = pkgs.runCommand "iw4x-rawfiles-0.2.36" {
    nativeBuildInputs = [ pkgs.unzip ];
  } ''
    unzip -q ${rawArchive} -d "$out"
    # Use the current client's layout to avoid migrating assets on every update.
    mkdir -p "$out/main/iw4x" "$out/zone/iw4x/x86"
    mv "$out/iw4x" "$out/main/iw4x/x86"
    mv "$out/zone/patch" "$out/zone/iw4x/x86/patch"
  '';
  bots = pkgs.runCommand "mw2-bot-warfare-2.3.0" {
    nativeBuildInputs = [ pkgs.unzip pkgs.zip ];
  } ''
    unzip -q ${botArchive}
    mkdir -p "$out"
    cp -r "Move files to root of MW2 folder/mods/mp_bots/." "$out/"
    # Analog sticks do not emit the menu's digital WASD commands. Keep the
    # upstream menu, using D-pad categories and triggers for its options.
    unzip -q "$out/z_svr_bots.iwd" maps/mp/bots/_menu.gsc
    substituteInPlace maps/mp/bots/_menu.gsc \
      --replace-fail '"+moveleft"' '"+actionslot 3"' \
      --replace-fail '"+moveright"' '"+actionslot 4"' \
      --replace-fail '"+forward"' '"+speed_throw"' \
      --replace-fail '"+back"' '"+attack"'
    zip -q "$out/z_svr_bots.iwd" maps/mp/bots/_menu.gsc
  '';
  dxvkConfig = pkgs.writeText "modern-warfare-2-dxvk.conf" ''
    d3d9.maxAvailableMemory = 1024
  '';
  launcher = pkgs.writeShellApplication {
    name = "modern-warfare-2";
    runtimeInputs = [ wine pkgs.coreutils pkgs.util-linux pkgs.python3 pkgs.xrandr pkgs.bubblewrap ];
    text = ''
      game="''${MW2_GAME_DIR:-''${XDG_DATA_HOME:-$HOME/.local/share}/games/modern-warfare-2}"
      for file in main/iw_00.iwd zone/english/common_mp.ff zone/english/patch_mp.ff; do
        if [[ ! -f "$game/$file" ]]; then
          echo "Modern Warfare 2 installation is incomplete: $game/$file" >&2
          exit 1
        fi
      done
      export WINEPREFIX="''${MW2_PREFIX:-''${XDG_DATA_HOME:-$HOME/.local/share}/wineprefixes/modern-warfare-2}"
      mkdir -p "$WINEPREFIX"
      exec 9>"$WINEPREFIX/.launcher.lock"
      flock -n 9 || exit 0
      logdir="''${XDG_STATE_HOME:-$HOME/.local/state}/modern-warfare-2"
      mkdir -p "$logdir"
      exec >"$logdir/last.log" 2>&1
      export WINEDEBUG="''${WINEDEBUG:--all}"
      export WINEDLLOVERRIDES="winemenubuilder.exe,mscoree,mshtml=d;d3d9=n"
      export DXVK_LOG_PATH="$logdir" DXVK_CONFIG_FILE=${dxvkConfig}
      if [[ ! -f "$WINEPREFIX/.mw2-controller-v1" ]]; then
        wineboot --init
        # SDL exposes DualSense as XInput; Wine's raw HID reports are incompatible
        # with the client's native DualSense driver.
        wine reg add 'HKLM\System\CurrentControlSet\Services\winebus' \
          /v 'Enable SDL' /t REG_DWORD /d 1 /f
        wine reg add 'HKLM\System\CurrentControlSet\Services\winebus' \
          /v DisableHidraw /t REG_DWORD /d 1 /f
        wineserver -w
        touch "$WINEPREFIX/.mw2-controller-v1"
      fi
      cp -f ${pkgs.dxvk.bin}/x32/d3d9.dll "$WINEPREFIX/drive_c/windows/syswow64/d3d9.dll"
      if [[ ! -f "$game/.nix-rawfiles-${rawFiles.name}" ]]; then
        cp -r --no-preserve=mode ${rawFiles}/. "$game/"
        touch "$game/.nix-rawfiles-${rawFiles.name}"
      fi
      cp -f ${client} "$game/iw4x.dll"
      mkdir -p "$game/mods/mp_bots"
      cp -r --no-preserve=mode ${bots}/. "$game/mods/mp_bots/"
      resolution=$(python3 ${./modern-warfare-2-settings.py} "$game")
      extra=()
      [[ -z "$resolution" ]] || extra+=(+set r_mode "$resolution")
      cd "$game"
      # Launch the menu: +map before first profile initialization crashes IW4x.
      # The onlinegame dvar enables local XP; net_ip confines the listen socket.
      bwrap --unshare-net --bind / / --dev-bind /dev /dev --proc /proc \
        wine iw4x.exe -nosteam -stdout -disable-mod-unloading \
        +set fs_game mods/mp_bots +set net_ip 127.0.0.1 \
        +set onlinegame 1 +set scr_rankedmatch 1 +set gpad_enabled 1 \
        "''${extra[@]}" "$@"
    '';
  };
in
{
  # The disc installation and x86 Wine runtime are local to top.
  config = lib.mkIf (host == "top") {
    home.packages = [ launcher ];
    xdg.desktopEntries.modern-warfare-2 = {
      name = "Modern Warfare 2 — Offline Bots";
      comment = "Bot Warfare with saved ranks and unlocks";
      exec = "${launcher}/bin/modern-warfare-2";
      icon = "${config.xdg.dataHome}/games/modern-warfare-2/mw2.png";
      categories = [ "Game" ];
      terminal = false;
      settings.StartupWMClass = "iw4x.exe";
    };
  };
}
