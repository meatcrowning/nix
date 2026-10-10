{ fetchurl, runCommand, libarchive }:
# The Unicode 6-era Symbola shipped in Quantal's ttf-ancient-fonts 2.57-1.
# Outline glyphs work in its FreeType/Pango; color emoji fonts do not.
let
  archive = fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/universe/t/ttf-ancient-fonts/ttf-ancient-fonts_2.57-1_all.deb";
    sha256 = "42574a59b55cb7c34da7816375316a4f7451def69468e979be89a2d8085dd4b1";
  };
in
runCommand "symbola-quantal-2.57" { nativeBuildInputs = [ libarchive ]; } ''
  mkdir extracted
  bsdtar -xOf ${archive} data.tar.gz | bsdtar -xf - -C extracted
  mkdir -p "$out/share/fonts/truetype" "$out/share/doc/symbola-quantal"
  cp extracted/usr/share/fonts/truetype/ttf-ancient-scripts/Symbola605.ttf "$out/share/fonts/truetype/Symbola.ttf"
  cp extracted/usr/share/doc/ttf-ancient-fonts/copyright "$out/share/doc/symbola-quantal/"
''
