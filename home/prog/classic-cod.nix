{ host, lib, pkgs, ... }:

let
  makeLauncher = { name, campaign, multiplayer, campaignArgs ? [] }: pkgs.writeShellApplication {
    inherit name;
    runtimeInputs = [ pkgs.wineWow64Packages.stable pkgs.coreutils pkgs.util-linux pkgs.bubblewrap ];
    text = ''
      game="''${XDG_DATA_HOME:-$HOME/.local/share}/games/${name}"
      mode=campaign
      if [[ "''${1:-}" == --multiplayer ]]; then
        mode=multiplayer
        shift
      elif [[ "''${1:-}" == --campaign ]]; then
        shift
      fi
      executable=${lib.escapeShellArg campaign}
      args=(${lib.escapeShellArgs campaignArgs})
      if [[ "$mode" == multiplayer ]]; then
        executable=${lib.escapeShellArg multiplayer}
        args=(${lib.optionalString (name == "modern-warfare-3") "-multiplayer"})
      fi
      for file in "$executable" main/iw_00.iwd zone/english/common.ff; do
        [[ -f "$game/$file" ]] || { echo "Incomplete ${name} installation: $game/$file" >&2; exit 1; }
      done
      export WINEPREFIX="''${XDG_DATA_HOME:-$HOME/.local/share}/wineprefixes/${name}"
      logdir="''${XDG_STATE_HOME:-$HOME/.local/state}/${name}"
      mkdir -p "$WINEPREFIX" "$logdir"
      exec 9>"$WINEPREFIX/.launcher.lock"
      flock -n 9 || exit 0
      exec >"$logdir/$mode.log" 2>&1
      export WINEDEBUG="''${WINEDEBUG:--all}"
      export WINEDLLOVERRIDES="winemenubuilder.exe,mscoree,mshtml=d;d3d9=n"
      export DXVK_LOG_PATH="$logdir"
      if [[ ! -f "$WINEPREFIX/.controller-v1" ]]; then
        wineboot --init
        wine reg add 'HKLM\System\CurrentControlSet\Services\winebus' \
          /v 'Enable SDL' /t REG_DWORD /d 1 /f
        wine reg add 'HKLM\System\CurrentControlSet\Services\winebus' \
          /v DisableHidraw /t REG_DWORD /d 1 /f
        wineserver -w
        touch "$WINEPREFIX/.controller-v1"
      fi
      cp -f ${pkgs.dxvk.bin}/x32/d3d9.dll "$WINEPREFIX/drive_c/windows/syswow64/d3d9.dll"
      cd "$game"
      bwrap --unshare-net --bind / / --dev-bind /dev /dev --proc /proc \
        wine "$executable" "''${args[@]}" +set net_ip 127.0.0.1 +set gpad_enabled 1 "$@"
    '';
  };
in
{
  # These locally extracted x86 disc installations belong to top.
  config = lib.mkIf (host == "top") {
    home.packages = [
      (makeLauncher {
        name = "call-of-duty-4";
        campaign = "iw3sp_mod.exe";
        multiplayer = "iw3mp.exe";
      })
      (makeLauncher {
        name = "modern-warfare-3";
        campaign = "iw5-mod.exe";
        campaignArgs = [ "-singleplayer" ];
        multiplayer = "iw5-mod.exe";
      })
    ];
  };
}
