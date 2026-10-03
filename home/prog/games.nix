{ config, host, pkgs, lib, ... }:

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
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ps.vdf ps.msgpack ps.pillow ]);
  games = pkgs.writeShellApplication {
    name = "games";
    runtimeInputs = [ python pkgs.icoutils pkgs.libnotify pkgs.hostname pkgs.procps ]
      ++ lib.optionals isX86 [ pkgs.umu-launcher retroarch pkgs.pcsx2 pkgs.steam-run pkgs.steam-rom-manager ];
    text = ''
      export GAMES_MANIFEST="''${GAMES_MANIFEST:-${config.home.homeDirectory}/nix/docs/games.$(hostname).json}"
      export GAMES_BIN=${config.home.profileDirectory}/bin/games
      export GAMES_RETROARCH_CORES=${if isX86 then "${retroarch}/lib/retroarch/cores" else "/nonexistent"}
      exec python3 ${./games-files}/games.py "$@"
    '';
  };
in
{
  # Steam ROM Manager puts every manifest game into Steam (`games steam`);
  # Ludusavi backs up their saves, configured by `games sync`.
  home.packages = [ games pkgs.ludusavi ] ++ lib.optionals isX86 [ retroarch pkgs.steam-rom-manager ];

  # ~/Games is the launcher folder itself, not a place for game files. Only
  # top's ~/Games was emptied for this; book's may still hold real files.
  home.file."Games" = lib.mkIf (host == "top") {
    source = config.lib.file.mkOutOfStoreSymlink "${config.xdg.dataHome}/plasma-games";
  };

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
