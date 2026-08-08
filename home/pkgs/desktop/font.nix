{ pkgs, lib, ... }:

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

  # Botis 4x6 — a hand-authored 4-wide blocky pixel face. There is NO 4x4 pixel
  # font on this system to merge or import from (the repo ships only the 8x16
  # DOS VGA pair, and fontconfig has only loose 8px IBM CGA faces), and the
  # user explicitly overrode the "do not invent a font" rule for this face — so
  # every pixel of every glyph is authored by hand in build-4x6.py. Authored
  # grid 4x6, baseline row 4, advance 5.
  #
  # It is emitted as a SCALABLE outline TTF (every authored pixel is a filled
  # square), NOT a bitmap. As a non-scalable BDF it was silently substituted by
  # every text stack that asks fontconfig for a scalable face —
  # `fc-match "Botis 4x6:scalable=true"` returned Noto Sans, and Pango (the
  # hyprvtb titlebar) and the Quickshell GL scenegraph both dropped it for a
  # generic sans, so the pick appeared to do nothing on those surfaces. The UPM
  # is chosen so that at the panel's 15px pixelSize each authored pixel is an
  # exact 2x2 device-pixel block — pixel-identical to the old 8x12 BDF — while
  # the font-size slider now scales it like any scalable face. Read the script
  # docstring for the grid, metrics and the UPM math before touching it.
  botis4x6 = pkgs.runCommand "botis-4x6" {
    nativeBuildInputs = [ (pkgs.python3.withPackages (ps: [ ps.fonttools ])) ];
  } ''
    mkdir -p $out/share/fonts/truetype
    python3 ${./font-files/build-4x6.py} $out/share/fonts/truetype/Botis4x6.ttf
  '';

  # Phenex — the hand-authored connected-script (cursive) face, the flowing
  # counterpart to Botis's blocky one; same rule override, same no-donor
  # provenance. Unlike the pixel faces it is a NORMAL smooth outline font:
  # every glyph is authored as a pen-skeleton of cubic strokes and FontForge's
  # stroke expansion sweeps a round nib along it (monoline script). Lowercase
  # share join anchors with zero side bearing, so words render as one
  # connected pen stroke. Named for the goetia's poet. It is the desktop's one
  # SMOOTH face: the `smooth` flag below drives antialiased rendering in
  # PixelText/deskstyle (a smooth face under the pixel pipeline is a jagged
  # staircase). Skeletons, joins and metrics: the script docstring.
  phenex = pkgs.runCommand "phenex" {
    nativeBuildInputs = [ pkgs.fontforge ];
  } ''
    mkdir -p $out/share/fonts/truetype
    fontforge -lang=py -script ${./font-files/build-phenex.py} \
      $out/share/fonts/truetype/Phenex.ttf
  '';

  # The desktop's SELECTABLE faces — the single source of truth for the
  # Settings "pixel font" dropdown (see FontFaces.qml generation below and
  # SetPgAppearance.qml). Each of these ships via the home.file installs and
  # fontconfig rules in this file. family is the fontconfig family name, which
  # is what settings.json's fontFamily stores and Theme.font /
  # DeskStyle.fontFamily resolve; label is the short lowercase name the
  # dropdown shows. Keep this list in step with the home.file/fontconfig
  # entries below: the Settings window enumerates from HERE, never its own
  # hardcoded copy. `smooth` marks a face that must be ANTIALIASED (a normal
  # outline face, not a pixel one): PixelText and deskstyle branch their
  # render path on it, via the generated singleton below and its deskstyle
  # twin (SMOOTH_FAMILIES in apps/pylib/deskstyle.py — keep the two in step).
  selectableFaces = [
    { family = "More Perfect DOS VGA"; label = "more perfect"; smooth = false; }
    { family = "Botis 4x6"; label = "botis 4x6"; smooth = false; }
    { family = "Phenex"; label = "phenex"; smooth = true; }
  ];

  # The Settings dropdown reads its options from a generated singleton rather
  # than a hardcoded QML array, so the two can never drift. Mirrors the
  # Host.qml pattern (home/prog/quickshell.nix): a store-path .qml that
  # Quickshell loads like any other singleton in the config dir.
  fontFacesQml = ''
    pragma Singleton
    import QtQuick

    QtObject {
        readonly property var families: [${lib.concatMapStringsSep "," (f: " \"${f.family}\"") selectableFaces} ]
        readonly property var labels: ({${lib.concatMapStringsSep "," (f: " \"${f.family}\": \"${f.label}\"") selectableFaces} })
        readonly property var smooth: ({${lib.concatMapStringsSep "," (f: " \"${f.family}\": ${lib.boolToString f.smooth}") selectableFaces} })
    }
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

  # The second, hand-authored pixel face — a 4-wide blocky pixel face shipped as
  # a SCALABLE outline TTF (see the derivation comment: a bitmap here was
  # silently substituted by Pango and the GL scenegraph). Not the live desktop
  # font; shipped as a selectable face like the two DOS ones, with its own
  # fontconfig rule below. It is NOT in nixpkgs and never will be — the whole
  # point is that it is invented here.
  home.file.".local/share/fonts/Botis4x6.ttf".source =
    "${botis4x6}/share/fonts/truetype/Botis4x6.ttf";

  # The third face — the hand-authored cursive script (see the derivation
  # comment above). Same selectable-face pattern as the pixel pair.
  home.file.".local/share/fonts/Phenex.ttf".source =
    "${phenex}/share/fonts/truetype/Phenex.ttf";

  # Generated singleton the Settings "pixel font" dropdown reads its options
  # from (SetPgAppearance.qml -> FontFaces). Built from `selectableFaces` above,
  # so the faces it offers and the home.file/fontconfig installs below can never
  # drift. Quickshell loads it from the config dir like any other singleton.
  xdg.configFile."quickshell/FontFaces.qml".text = fontFacesQml;

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

  # Botis 4x6 ships Regular-only too (a single outline face), so it gets the
  # same guard: pin any request for it to upright regular and kill synthetic
  # emboldening, so the pixel squares are never faux-bolded/obliqued into a smear.
  xdg.configFile."fontconfig/conf.d/50-botis-4x6-regular.conf".text = ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
      <match target="pattern">
        <test name="family"><string>Botis 4x6</string></test>
        <edit name="weight"   mode="assign"><const>regular</const></edit>
        <edit name="slant"    mode="assign"><const>roman</const></edit>
        <edit name="embolden" mode="assign"><bool>false</bool></edit>
      </match>
      <match target="font">
        <test name="family"><string>Botis 4x6</string></test>
        <edit name="embolden" mode="assign"><bool>false</bool></edit>
      </match>
    </fontconfig>
  '';

  # Phenex ships Regular-only too, and gets the same upright-regular pin — but
  # the OPPOSITE rasterisation: it is the desktop's one smooth face, so every
  # fontconfig consumer (Pango titlebar, kitty, GTK, qutebrowser) must
  # antialias it and must NOT hint it. It ships unhinted, and the autohinter
  # visibly kinks the connected baseline joins at small sizes (its strong
  # vertical-stem model fights a monoline script); grayscale AA rather than
  # subpixel keeps the thick curved strokes free of colour fringes.
  xdg.configFile."fontconfig/conf.d/50-phenex-regular.conf".text = ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
      <match target="pattern">
        <test name="family"><string>Phenex</string></test>
        <edit name="weight"   mode="assign"><const>regular</const></edit>
        <edit name="slant"    mode="assign"><const>roman</const></edit>
        <edit name="embolden" mode="assign"><bool>false</bool></edit>
      </match>
      <match target="font">
        <test name="family"><string>Phenex</string></test>
        <edit name="embolden"  mode="assign"><bool>false</bool></edit>
        <edit name="antialias" mode="assign"><bool>true</bool></edit>
        <edit name="autohint"  mode="assign"><bool>false</bool></edit>
        <edit name="hinting"   mode="assign"><bool>false</bool></edit>
        <edit name="hintstyle" mode="assign"><const>hintnone</const></edit>
        <edit name="rgba"      mode="assign"><const>none</const></edit>
      </match>
    </fontconfig>
  '';
}
