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

  # The size-adjusted WEB twin of the merged face: same outlines/advances/
  # vertical metrics at 1.14x, installed as its own family (" (web)"). This is
  # the font-file replacement for the @font-face size-adjust alias surfer used
  # to carry — the alias forced Chromium grayscale-AA on every web glyph, the
  # real face goes through fontconfig and honours the antialias=false pin, so
  # site text at the site's own sizes reads the proportional x-height AND
  # pixel-crisp (measured offscreen 2026-08-09; the whole story and the
  # numbers are in scale-vga.py's docstring and apps/surfer/main.py's
  # _XHEIGHT_ADJUST). Factor is the default pick's x-height adjust; another
  # pick has its own ratio and would need its own measured factor.
  morePerfectDOSVGAWeb = pkgs.runCommand "more-perfect-dos-vga-web" {
    nativeBuildInputs = [ (pkgs.python3.withPackages (ps: [ ps.fonttools ])) ];
  } ''
    python3 ${./font-files/scale-vga.py} \
      ${morePerfectDOSVGA}/share/fonts/truetype/MorePerfectDOSVGA.ttf \
      $out/share/fonts/truetype/MorePerfectDOSVGA-web.ttf \
      1.14 " (web)"
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
  # Two stages: FontForge draws and strokes the glyphs (incl. the .a1/.a2/.fin
  # lowercase variants); fontTools then compiles the `calt` feature that
  # cycles the alternates and substitutes word-final forms — FontForge's own
  # python cannot host feaLib, hence the split.
  phenex = pkgs.runCommand "phenex" {
    nativeBuildInputs = [
      pkgs.fontforge
      (pkgs.python3.withPackages (ps: [ ps.fonttools ]))
    ];
  } ''
    mkdir -p $out/share/fonts/truetype
    fontforge -lang=py -script ${./font-files/build-phenex.py} --draw base.ttf
    python3 ${./font-files/build-phenex.py} --features base.ttf \
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
    # Terminus — the classic monospace BITMAP face (family "Terminus"). The
    # package ships PCF bitmaps at fixed pixel sizes (ter-x*.pcf.gz); it has
    # NO scalable outline, so it is served from its embedded bitmaps and its
    # fontconfig rule below turns antialiasing and autohinting off so nothing
    # tries to smooth or grid-fit a 1-bit bitmap. Bold variants ship too, so
    # no single-weight regular pin (unlike the hand-authored faces).
    terminus_font
  ];

  # Not in nixpkgs — quickshell's Theme.qml and kitty.conf both depend on it.
  # Same family name and same runtime path as the unmerged font it replaced;
  # everything that names the family keeps working untouched.
  home.file.".local/share/fonts/MorePerfectDOSVGA.ttf".source =
    "${morePerfectDOSVGA}/share/fonts/truetype/MorePerfectDOSVGA.ttf";

  # The size-adjusted web twin (see the derivation comment): installed
  # alongside the base face so fontconfig can match it by family name. Only
  # surfer's CSS ever asks for it; the desktop itself keeps the plain face.
  home.file.".local/share/fonts/MorePerfectDOSVGA-web.ttf".source =
    "${morePerfectDOSVGAWeb}/share/fonts/truetype/MorePerfectDOSVGA-web.ttf";

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

  # Cozette VECTOR — the OUTLINE build of Cozette (family "CozetteVector"),
  # not the bitmap .bdf/.otb the same package also ships. We install only the
  # two scalable TTFs (regular + bold) so the bitmap "Cozette" family is NOT
  # registered: the vector build is what renders on a scalable text stack (the
  # Botis lesson — a non-scalable face is silently substituted). It is a
  # pixel-DESIGN font in outline form, so its fontconfig rule below draws it
  # grayscale with rgba=none per the desktop convention (§2.1).
  home.file.".local/share/fonts/CozetteVector.ttf".source =
    "${pkgs.cozette}/share/fonts/truetype/CozetteVector.ttf";
  home.file.".local/share/fonts/CozetteVectorBold.ttf".source =
    "${pkgs.cozette}/share/fonts/truetype/CozetteVectorBold.ttf";

  # Generated singleton the Settings "pixel font" dropdown reads its options
  # from (SetPgAppearance.qml -> FontFaces). Built from `selectableFaces` above,
  # so the faces it offers and the home.file/fontconfig installs below can never
  # drift. Quickshell loads it from the config dir like any other singleton.
  xdg.configFile."quickshell/FontFaces.qml".text = fontFacesQml;

  # The same list for SCRIPTS (family -> smooth flag): apply-pixel-font.sh
  # jq's it to tell the hyprvtb titlebar whether the pushed face is smooth
  # (plugin:hyprvtb:font_smooth), so the plugin's cairo AA choice follows the
  # face without hardcoding a family name anywhere outside this file.
  xdg.configFile."quickshell/font-faces.json".text = builtins.toJSON
    (lib.listToAttrs (map (f: lib.nameValuePair f.family { inherit (f) smooth; }) selectableFaces));

  # "More Perfect DOS VGA" ships ONLY a Regular face. Without this, KDE/Qt apps
  # faux-bold (and oblique-shear) it wherever the UI asks for bold/italic text —
  # info-panel labels, selected tabs, section headers, etc. On a pixel font
  # that's already scaled off its 16px grid, the synthetic bold smears and reads
  # as a heavier, slightly larger, different typeface beside the regular glyphs
  # (see kdeglobals — every font role is this family at 11pt, so nothing else
  # explains the size/format mismatch). Pin every request for this family to
  # upright regular and kill synthetic emboldening, so all its text stays
  # uniform. Trade-off: bold emphasis is intentionally dropped for this font.
  #
  # The rasterisation pins are the fontconfig half of the pixel pipeline
  # (docs/DESIGN.md §2.2): PixelText and deskstyle keep Qt-land crisp, and
  # hyprvtb forces its own cairo options, but every OTHER fontconfig consumer
  # (GTK, qutebrowser, kdialog…) fell to platform defaults — measured through
  # Pango: 26 grey levels on this face at 15px. Platform defaults also DIFFER
  # per host (NixOS vs book's Fedora), so without the pins the same face
  # renders differently on the two machines — and on book's 1.67-scale Retina
  # the default grayscale AA smears the fractionally-scaled squares outright.
  # antialias off + FULL autohinting + rgba none = the authored squares,
  # mono-rendered, identically everywhere. The hint mode matters: hintnone
  # (the first cut, bc631b5) matched "the authored squares" reasoning but
  # contradicted the desktop's own reference pipeline — PixelText and
  # deskstyle.editorFont rasterise with PreferFullHinting, which is where the
  # 8px advance of DESIGN §2.1's 8x15 kitty cell comes from (the face is
  # authored 9 units wide per 16: advance 2304/4096 em = 8.4375 at 15px, and
  # only grid-fitting rounds it to 8). kitty honours the hinting pin, so
  # hintnone gave it the unhinted 8.4375 -> a 9px cell and ragged fractional
  # glyphs — [his] "more perfect ... no longer look[s] sharp and crisp in
  # kitty". Measured on the sandbox output 2026-08-08: hintnone = 9px
  # advances, uneven stems; autohint+hintfull = uniform 8px advances, near-
  # mono edges, and Chromium canvas parity with QML holds (tools/../
  # font-parity: greys 1, identical ink and advances).
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
        <edit name="embolden"  mode="assign"><bool>false</bool></edit>
        <edit name="antialias" mode="assign"><bool>false</bool></edit>
        <edit name="autohint"  mode="assign"><bool>true</bool></edit>
        <edit name="hinting"   mode="assign"><bool>true</bool></edit>
        <edit name="hintstyle" mode="assign"><const>hintfull</const></edit>
        <edit name="rgba"      mode="assign"><const>none</const></edit>
      </match>
    </fontconfig>
  '';

  # The same pins for the size-adjusted web twin (family name "More Perfect
  # DOS VGA (web)"). This is the half that makes the twin work: without a
  # font-level antialias=false on the NEW family name, fontconfig falls back
  # to Chromium's default grayscale AA for it and the twin blurs exactly like
  # the @font-face alias it replaces (the pin on the plain name does not
  # reach it — the twin's family is its own name). Mirror the base rule so
  # the scaled face rasterises pixel-crisp everywhere the plain one does.
  xdg.configFile."fontconfig/conf.d/50-more-perfect-dos-vga-web-regular.conf".text = ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
      <match target="pattern">
        <test name="family"><string>More Perfect DOS VGA (web)</string></test>
        <edit name="weight"   mode="assign"><const>regular</const></edit>
        <edit name="slant"    mode="assign"><const>roman</const></edit>
        <edit name="embolden" mode="assign"><bool>false</bool></edit>
      </match>
      <match target="font">
        <test name="family"><string>More Perfect DOS VGA (web)</string></test>
        <edit name="embolden"  mode="assign"><bool>false</bool></edit>
        <edit name="antialias" mode="assign"><bool>false</bool></edit>
        <edit name="autohint"  mode="assign"><bool>true</bool></edit>
        <edit name="hinting"   mode="assign"><bool>true</bool></edit>
        <edit name="hintstyle" mode="assign"><const>hintfull</const></edit>
        <edit name="rgba"      mode="assign"><const>none</const></edit>
      </match>
    </fontconfig>
  '';

  # Botis 4x6 ships Regular-only too (a single outline face), so it gets the
  # same guard: pin any request for it to upright regular and kill synthetic
  # emboldening, so the pixel squares are never faux-bolded/obliqued into a
  # smear. Same antialias/rgba pins as the VGA face above — but UNHINTED,
  # unlike it. Any grid fit (auto- or light hinting) snaps this face's
  # horizontal edges to the device grid, and at any size off the exact 2x2
  # grid (15px) that sliced every glyph with blank horizontal lines (measured
  # 2026-08-08: 'H' at 11-20px carried 2-4 full white rows under
  # autohint+hintfull; unhinted is contiguous at every size, and at 15px the
  # two are pixel-identical). The VGA face keeps hintfull because kitty's
  # 8x15 cell needs the grid-fitted 8px advance; nothing pins Botis to a
  # size, so it must survive arbitrary ones instead. Two consumers needed
  # more than this pin: build-4x6.py now emits MERGED union outlines (per-
  # pixel square contours had seams a hinting rasteriser pulls apart), and
  # Chromium ignores hinting pins outright for aliased faces — surfer layers
  # its own Botis antialias carve-out over this config (home/prog/surfer.nix,
  # the measurements are there).
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
        <edit name="embolden"  mode="assign"><bool>false</bool></edit>
        <edit name="antialias" mode="assign"><bool>false</bool></edit>
        <edit name="autohint"  mode="assign"><bool>false</bool></edit>
        <edit name="hinting"   mode="assign"><bool>false</bool></edit>
        <edit name="hintstyle" mode="assign"><const>hintnone</const></edit>
        <edit name="rgba"      mode="assign"><const>none</const></edit>
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

  # Cozette Vector — the outline build of a pixel-design font (family
  # "CozetteVector", installed by the home.file above). It is a normal
  # scalable face with regular + bold, so no weight pin. Rendering: the
  # desktop's grayscale rgba=none convention (§2.1) — antialias ON but no LCD
  # subpixel, so no colour fringes on either host. It ships its own outline
  # hinting; autohint is left OFF (the autohinter reshapes a pixel-derived
  # outline) and slight hinting keeps the near-vertical/horizontal pixel stems
  # on the grid without the heavy grid-fit a pixel-font full-hint would force.
  # embeddedbitmap off: the TTF carries no bitmap strike, this only makes the
  # intent explicit.
  xdg.configFile."fontconfig/conf.d/50-cozette-vector.conf".text = ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
      <match target="font">
        <test name="family"><string>CozetteVector</string></test>
        <edit name="antialias"      mode="assign"><bool>true</bool></edit>
        <edit name="autohint"       mode="assign"><bool>false</bool></edit>
        <edit name="hinting"        mode="assign"><bool>true</bool></edit>
        <edit name="hintstyle"      mode="assign"><const>hintslight</const></edit>
        <edit name="rgba"           mode="assign"><const>none</const></edit>
        <edit name="embeddedbitmap" mode="assign"><bool>false</bool></edit>
      </match>
    </fontconfig>
  '';

  # Terminus — a pure BITMAP face (family "Terminus", from terminus_font).
  # Render it from its EMBEDDED BITMAPS and never smooth or grid-fit them:
  # embeddedbitmap ON, antialias OFF (a 1-bit strike has nothing to
  # antialias — grayscale AA only blurs the exact pixels), autohint/hinting
  # OFF (there is no outline to hint; the autohinter would mangle the strike).
  # rgba=none keeps it off the LCD-subpixel path like the rest of the desktop.
  # Bold ships in the package, so no single-weight regular pin.
  xdg.configFile."fontconfig/conf.d/50-terminus-bitmap.conf".text = ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
      <match target="font">
        <test name="family"><string>Terminus</string></test>
        <edit name="embeddedbitmap" mode="assign"><bool>true</bool></edit>
        <edit name="antialias"      mode="assign"><bool>false</bool></edit>
        <edit name="autohint"       mode="assign"><bool>false</bool></edit>
        <edit name="hinting"        mode="assign"><bool>false</bool></edit>
        <edit name="hintstyle"      mode="assign"><const>hintnone</const></edit>
        <edit name="rgba"           mode="assign"><const>none</const></edit>
      </match>
    </fontconfig>
  '';

  # Tahoma — proprietary Microsoft TrueType. This is the RENDERING rule only;
  # the font binary itself is NOT installed here and cannot be: ~/nix is a
  # public repo and Tahoma is not in any free-redistributable pack (corefonts,
  # vista-fonts). On `top` the user's own copy already sits at
  # ~/.local/share/fonts/tahoma.ttf, so this rule takes effect there; on `book`
  # it applies only once the file is placed by hand. Tahoma is superbly
  # bytecode-hinted, so use its NATIVE full hinting (autohint off, hintfull)
  # with grayscale AA and rgba=none — the classic ClearType-off look, matching
  # the desktop convention (§2.1). No weight pin: Tahoma has a real Bold; the
  # user may add tahomabd.ttf. See the board ask on legally sourcing it.
  xdg.configFile."fontconfig/conf.d/50-tahoma.conf".text = ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
      <match target="font">
        <test name="family"><string>Tahoma</string></test>
        <edit name="antialias"      mode="assign"><bool>true</bool></edit>
        <edit name="autohint"       mode="assign"><bool>false</bool></edit>
        <edit name="hinting"        mode="assign"><bool>true</bool></edit>
        <edit name="hintstyle"      mode="assign"><const>hintfull</const></edit>
        <edit name="rgba"           mode="assign"><const>none</const></edit>
        <edit name="embeddedbitmap" mode="assign"><bool>false</bool></edit>
      </match>
    </fontconfig>
  '';
}
