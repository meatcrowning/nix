# Let Konsole's terminal surface be painted by the active KStyle when its
# dynamic scheme asks for `Wallpaper=StyleBackground`.  That is how Oxygen can
# carry its real titlebar/window gradient through the terminal body: a static
# Konsole wallpaper has neither the parent window's geometry nor its radial
# highlight.  The scheme itself is still regenerated live by konsole-theme.
final: prev: {
  kdePackages = prev.kdePackages // {
    konsole = prev.kdePackages.konsole.overrideAttrs (old: {
      patches = (old.patches or []) ++ [ ../home/prog/konsole-style-background.patch ];
    });
  };
}
