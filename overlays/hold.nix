# Packages held at nixpkgs-hold while the main nixpkgs input rolls. Remove a
# name here to let it follow nixpkgs again; drop the input when the set is
# empty. The ollama-cuda overlay applies inside the held set so its store
# path stays the one already built.
{ inputs }:
final: prev:
let
  system = prev.stdenv.hostPlatform.system;
  held = import inputs.nixpkgs-hold {
    inherit system;
    config = {
      allowUnfree = true;
      cudaCapabilities = [ "12.0" ];
    };
    overlays = [ (import ./ollama-cuda.nix) ];
  };
in
{
  inherit (held) firefox ollama ollama-cuda;
  # pad's desktop is nixpkgs Hyprland; top and book use the pinned flake inputs.
  inherit (held) hyprland xdg-desktop-portal-hyprland;
}
