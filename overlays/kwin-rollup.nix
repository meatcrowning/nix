# Roll up ("shade") a window from its titlebar, in the Plasma session.
# KWin removed shading, but only its own half of the seam: KDecoration3
# still has DecorationButtonType::Shade, and Breeze and Oxygen both still
# build the button, draw its icon and render a shaded frame. What is gone is
# three stubs in src/decorations/decoratedwindow.cpp (isShadeable/isShaded/
# requestToggleShade, answering false/false/nothing) and the 'L' character in
# the two button tables, so the button cannot be placed or listed. The patch
# restores exactly that: roll the frame down to the decoration's top border,
# remember the height, roll back — a rolled-up window is an ordinary resized
# window — plus 'L' and a "Roll up window" entry in the decoration KCM's
# draggable palette. Costs a from-source kwin build on every nixpkgs bump,
# and a patch refresh whenever upstream touches those files. Merge-override
# for the same reason as breeze above: the session runs the kwin_wayland
# binary the plasma6 module puts in systemPackages, so only kwin itself has
# to rebuild, not the Plasma stack that build-depends on it.
final: prev: {
  kdePackages = prev.kdePackages // {
    kwin = prev.kdePackages.kwin.overrideAttrs (old: {
      patches = (old.patches or []) ++ [ ../sys/dsk/kwin-roll-up-button.patch ];
    });
  };
}
