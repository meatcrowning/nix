{ ... }:

{
  # Persists the Settings "border width" / "corner rounding" pick into the live
  # hyprland.lua, so a config reload cannot revert it. The panel's live
  # `hl.config` push is a runtime override only; anything that autoreloads
  # hyprland.lua (apply-pixel-font.sh's font seds, a plain `hyprctl reload`)
  # dropped it back to whatever that file still said — which is how changing the
  # pixel font reset the corner radius. Called debounced from
  # SettingsApply.qml; wal-set.sh writes the same two lines at every theme apply.
  xdg.configFile."scripts/apply-window-frame.sh" = {
    source = ./window-frame-files/apply-window-frame.sh;
    executable = true;
  };
}
