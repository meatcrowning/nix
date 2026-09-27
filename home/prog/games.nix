{ config, pkgs, lib, ... }:

# Launchers for games outside Steam. The per-host manifest lives in the private
# docs repo (docs/games.<hostname>.json) because it lists the user's own files;
# a host without one simply gets no launchers. The Plasma games folder
# (plasma-games.nix) collects the generated entries alongside Steam's.
let
  isX86 = pkgs.stdenv.hostPlatform.isx86_64;
  retroarch = pkgs.retroarch.withCores (cores: with cores; [
    swanstation
    dolphin
    mupen64plus
    mgba
    snes9x
    fceumm
    ppsspp
  ]);
  games = pkgs.writeShellApplication {
    name = "games";
    runtimeInputs = [ pkgs.python3 pkgs.icoutils pkgs.libnotify pkgs.hostname ]
      ++ lib.optionals isX86 [ pkgs.umu-launcher retroarch pkgs.pcsx2 pkgs.steam-run ];
    text = ''
      export GAMES_MANIFEST="''${GAMES_MANIFEST:-${config.home.homeDirectory}/nix/docs/games.$(hostname).json}"
      export GAMES_RETROARCH_CORES=${if isX86 then "${retroarch}/lib/retroarch/cores" else "/nonexistent"}
      exec python3 ${./games-files/games.py} "$@"
    '';
  };
in
{
  home.packages = [ games ] ++ lib.optionals isX86 [ retroarch ];

  # Icon extraction reads the games' drives and box art comes from the
  # network, so keep both off the activation path.
  home.activation.syncGames = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${pkgs.systemd}/bin/systemctl --user start --no-block games-sync.service || true
  '';

  systemd.user.services.games-sync = {
    Unit.Description = "write game launchers from the games manifest";
    Service = {
      Type = "oneshot";
      ExecStart = "${games}/bin/games sync";
    };
  };
}
