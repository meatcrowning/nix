# Quantal's text metrics, hinting and rasterization are part of the interface.
{ runCommand, runtime, lib, glib, cairo, pango, fontconfig, freetype, harfbuzz, expat, zlib
, libX11, libXrender, libXft, libxcb, pixman, stdenv }:
runCommand "unity-historical-text" {} ''
  mkdir -p "$out/lib/pkgconfig" "$out/etc/pango"
  for name in pango-1.0 pangocairo-1.0 pangoft2-1.0 pangoxft-1.0 pangox-1.0 Xft freetype fontconfig cairo cairo-gobject pixman-1 png12; do
    original=$(find ${runtime}/usr/lib ${runtime}/lib -name "lib$name.so.*" -type f | head -1)
    cp "$original" "$out/lib/"
    target="$out/lib/$(basename "$original")"
    chmod u+w "$target"
    patchelf --set-rpath "$out/lib:${lib.makeLibraryPath [ glib cairo expat zlib libX11 libXrender libXft libxcb pixman stdenv.cc.cc.lib ]}" "$target"
    ln -s "$(basename "$original")" "$out/lib/lib$name.so"
    soname=$(patchelf --print-soname "$target")
    ln -s "$(basename "$original")" "$out/lib/$soname"
  done
  cp -r ${runtime}/usr/lib/x86_64-linux-gnu/pango "$out/lib/"
  chmod -R u+w "$out/lib/pango"
  for module in "$out"/lib/pango/1.6.0/modules/*.so; do
    patchelf --set-rpath "$out/lib:${lib.makeLibraryPath [ glib cairo libX11 libXft ]}" "$module"
  done
  sed "s|/usr/lib/x86_64-linux-gnu/pango|$out/lib/pango|g" \
    "$out/lib/pango/1.6.0/module-files.d/libpango1.0-0.modules" > "$out/etc/pango/pango.modules"
  printf '[Pango]\nModuleFiles=%s/etc/pango/pango.modules\n' "$out" > "$out/etc/pango/pangorc"
  # Build against modern declarations only for the stable APIs used by GTK 3.6.
  for pc in ${pango.dev}/lib/pkgconfig/*.pc ${fontconfig.dev}/lib/pkgconfig/*.pc ${freetype.dev}/lib/pkgconfig/*.pc; do
    sed -e "s|^libdir=.*|libdir=$out/lib|" -e 's/^Requires:.*$/Requires: glib-2.0 gobject-2.0/' -e '/^Requires.private:/d' -e 's|^Cflags:|Cflags: -I${harfbuzz.dev}/include/harfbuzz|' "$pc" > "$out/lib/pkgconfig/$(basename "$pc")"
  done
  for pc in ${cairo.dev}/lib/pkgconfig/*.pc; do
    sed -e "s|^libdir=.*|libdir=$out/lib|" "$pc" > "$out/lib/pkgconfig/$(basename "$pc")"
  done
  sed -e 's|/usr/share/fonts|${runtime}/usr/share/fonts|g' \
      -e 's|/etc/fonts|${runtime}/etc/fonts|g' \
      ${runtime}/etc/fonts/fonts.conf > "$out/etc/fonts.conf"
  mkdir -p "$out/lib/girepository-1.0"
  cp ${runtime}/usr/lib/girepository-1.0/Pango-*.typelib "$out/lib/girepository-1.0/"
''
