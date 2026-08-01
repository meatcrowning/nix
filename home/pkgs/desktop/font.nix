{ pkgs, ... }:

let
  # More Perfect DOS VGA, plus the 526 codepoints it lacks, imported from PxPlus
  # IBM VGA 9x16 (same 8x16 VGA design, same em-relative grid, so the import is
  # exact and every original glyph is untouched). 255 -> 781 codepoints; the
  # ellipsis is in, by his call on tools/font-demo. The whole rationale and the
  # guarantees are in the script — read that before changing anything here.
  #
  # A script and not a committed .ttf on purpose: the donor is CC BY-SA 4.0, so
  # the merged file is Adapted Material, and this repo is public.
  morePerfectDOSVGA = pkgs.runCommand "more-perfect-dos-vga-merged" {
    nativeBuildInputs = [ (pkgs.python3.withPackages (ps: [ ps.fonttools ])) ];
  } ''
    python3 ${./font-files/merge-vga.py} \
      ${./font-files/MorePerfectDOSVGA.ttf} \
      ${pkgs.ultimate-oldschool-pc-font-pack}/share/fonts/truetype/PxPlus_IBM_VGA_9x16.ttf \
      $out/share/fonts/truetype/MorePerfectDOSVGA.ttf \
      "More Perfect DOS VGA"
  '';

  # Perfect DOS VGA 437 — the other face in the same 8x16 DOS VGA family (the one
  # Zeh Fernando made first; More Perfect is its refinement). Vendored, because
  # it is not in nixpkgs: source _home/pkgs/desktop/font-files/PerfectDOSVGA437.ttf_
  # (.ttf pulled from bh/cool-old-term@master, itself Zeh Fernando's
  # fatorcaos.com.br face — free for personal and commercial use). Like More
  # Perfect it covers only its 437-page glyphs, so the same PxPlus import applies
  # (256 -> 788, existing glyphs untouched) — otherwise switching to it would
  # reintroduce the DESIGN.md S2.3 clipping. Exposed as its own family name.
  perfectDOSVGA437 = pkgs.runCommand "perfect-dos-vga-437-merged" {
    nativeBuildInputs = [ (pkgs.python3.withPackages (ps: [ ps.fonttools ])) ];
  } ''
    python3 ${./font-files/merge-vga.py} \
      ${./font-files/PerfectDOSVGA437.ttf} \
      ${pkgs.ultimate-oldschool-pc-font-pack}/share/fonts/truetype/PxPlus_IBM_VGA_9x16.ttf \
      $out/share/fonts/truetype/PerfectDOSVGA437.ttf \
      "Perfect DOS VGA 437"
  '';
in

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
  # Same family name and same runtime path as the unmerged font it replaced;
  # everything that names the family keeps working untouched.
  home.file.".local/share/fonts/MorePerfectDOSVGA.ttf".source =
    "${morePerfectDOSVGA}/share/fonts/truetype/MorePerfectDOSVGA.ttf";

  # The second pixel face. Same runtime-dir pattern, its own family name, on
  # both hosts (this is home/, not sys/). settings.json's fontFamily points at
  # whichever face is live; both resolve here.
  home.file.".local/share/fonts/PerfectDOSVGA437.ttf".source =
    "${perfectDOSVGA437}/share/fonts/truetype/PerfectDOSVGA437.ttf";

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

  # Perfect DOS VGA 437 also ships Regular-only, so the same faux-bold rule must
  # cover it — otherwise a switch to the second face brings the smearing back.
  xdg.configFile."fontconfig/conf.d/50-perfect-dos-vga-437-regular.conf".text = ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
      <match target="pattern">
        <test name="family"><string>Perfect DOS VGA 437</string></test>
        <edit name="weight"   mode="assign"><const>regular</const></edit>
        <edit name="slant"    mode="assign"><const>roman</const></edit>
        <edit name="embolden" mode="assign"><bool>false</bool></edit>
      </match>
      <match target="font">
        <test name="family"><string>Perfect DOS VGA 437</string></test>
        <edit name="embolden" mode="assign"><bool>false</bool></edit>
      </match>
    </fontconfig>
  '';
}
