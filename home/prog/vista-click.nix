{ config, pkgs, lib, ... }:

{
  # "Vista Navigation Click" Vivaldi/Chromium extension: plays the Vista
  # Navigation Start sound on web link clicks (IE-style). Chromium can't be
  # told about unpacked extensions declaratively, so this stages the
  # extension dir and the user loads it ONCE via
  # vivaldi://extensions -> developer mode -> "Load unpacked" ->
  # ~/.local/share/vista-click-extension (the path is stable; updates land
  # through these symlinks automatically).
  home.file.".local/share/vista-click-extension/manifest.json".source = ./vista-click-extension/manifest.json;
  home.file.".local/share/vista-click-extension/content.js".source = ./vista-click-extension/content.js;

  # The wav is Microsoft's and this repo is public, so it is NOT tracked —
  # copied in from the user's local Vista set at activation, if present.
  home.activation.vistaClickWav = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    src="$HOME/.local/share/sounds/vista/Windows Navigation Start.wav"
    dst="$HOME/.local/share/vista-click-extension/click.wav"
    [ -f "$src" ] && [ ! -e "$dst" ] && cp "$src" "$dst" || true
  '';
}
