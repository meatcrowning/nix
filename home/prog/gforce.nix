{ pkgs, ... }:

# gforce — the G-Force (classic iTunes) visualizer prototype, on both hosts.
# The engine source has unclear licensing, so it stays out of this public repo:
# it lives in the private docs repo, and this wrapper only hands off to
# docs/agents/gforce-install.sh, which builds it (nixpkgs toolchain on top,
# Fedora's on book) on the first launch after an update and then runs it.
# Details: docs/agents/player-visualizer-handoff.md.
let
  gforce = pkgs.writeShellScriptBin "gforce" ''
    installer=/home/lam/nix/docs/agents/gforce-install.sh
    if [ ! -x "$installer" ]; then
      msg="needs the private docs repo at ~/nix/docs (nix-docs-sync)"
      echo "gforce: $msg" >&2
      command -v notify-send >/dev/null && notify-send -- gforce "$msg"
      exit 1
    fi
    exec "$installer" --launch "$@"
  '';
in
{
  home.packages = [ gforce ];

  home.file.".local/share/applications/gforce.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=gforce
    GenericName=Music Visualizer
    Comment=Classic iTunes-style visualizer of desktop audio
    Exec=${gforce}/bin/gforce
    Icon=multimedia-audio-player
    Terminal=false
    Categories=AudioVideo;Audio;
    Keywords=visualizer;itunes;g-force;
  '';
}
