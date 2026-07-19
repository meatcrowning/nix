{ pkgs, ... }:

{
  home.packages = with pkgs; [
    cascadia-code
    source-code-pro
    mononoki
    vista-fonts
    noto-fonts-color-emoji
    oxygenfonts
  ];

  # Not in nixpkgs — quickshell's Theme.qml and kitty.conf both depend on it.
  home.file.".local/share/fonts/MorePerfectDOSVGA.ttf".source =
    ./font-files/MorePerfectDOSVGA.ttf;

  # "More Perfect DOS VGA" ships ONLY a Regular face. Without this, KDE/Qt apps
  # faux-bold (and oblique-shear) it wherever the UI asks for bold/italic text —
  # info-panel labels, selected tabs, section headers, etc. On a pixel font
  # that's already scaled off its 16px grid, the synthetic bold smears and reads
  # as a heavier, slightly larger, different typeface beside the regular glyphs
  # (see kdeglobals — every font role is this family at 11pt, so nothing else
  # explains the size/format mismatch). Pin every request for this family to
  # upright regular and kill synthetic emboldening, so all its text stays
  # uniform. Trade-off: bold emphasis is intentionally dropped for this font.
  xdg.configFile."fontconfig/conf.d/50-more-perfect-dos-vga-regular.conf".text = ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
      <match target="pattern">
        <test name="family"><string>More Perfect DOS VGA</string></test>
        <edit name="weight"   mode="assign"><const>regular</const></edit>
        <edit name="slant"    mode="assign"><const>roman</const></edit>
        <edit name="embolden" mode="assign"><bool>false</bool></edit>
      </match>
      <match target="font">
        <test name="family"><string>More Perfect DOS VGA</string></test>
        <edit name="embolden" mode="assign"><bool>false</bool></edit>
      </match>
    </fontconfig>
  '';
}
