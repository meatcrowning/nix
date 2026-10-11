{ runCommand, stdenv, runtime, freetype, zlib, lib, patchelf }:
runCommand "unity-terminal-historical-rasterizer" {
  nativeBuildInputs = [ stdenv.cc patchelf ];
} ''
  mkdir -p "$out/lib" "$out/etc/fonts"
  cp -Lr ${runtime}/etc/fonts/conf.d "$out/etc/fonts/"
  # Modern Fontconfig no longer accepts the obsolete blank-character list or
  # aliases nested inside match. Keep the original rules with valid syntax.
  sed -e 's|/usr/share/fonts|${runtime}/usr/share/fonts|g' \
      -e "s|/etc/fonts|$out/etc/fonts|g" -e '/<blank>/,/<\/blank>/d' \
      ${runtime}/etc/fonts/fonts.conf > "$out/etc/fonts/fonts.conf"
  chmod u+w "$out/etc/fonts/conf.d" "$out/etc/fonts/conf.d/65-khmer.conf"
  sed -i -e '/<match target="font">/d' -e '/<\/match>/d' "$out/etc/fonts/conf.d/65-khmer.conf"
  cp ${runtime}/usr/lib/x86_64-linux-gnu/libfreetype.so.6 "$out/lib/libfreetype-quantal.so.6"
  chmod u+w "$out/lib/libfreetype-quantal.so.6"
  patchelf --set-soname libfreetype-quantal.so.6 --set-rpath ${lib.makeLibraryPath [ zlib ]} \
    "$out/lib/libfreetype-quantal.so.6"
  $CC -Wall -Wextra -Werror -shared -fPIC -O2 -I${freetype.dev}/include/freetype2 \
    ${./terminal-freetype.c} -Wl,-soname,libfreetype.so.6 -Wl,-rpath,"$out/lib" \
    -Wl,--no-as-needed "$out/lib/libfreetype-quantal.so.6" -o "$out/lib/libfreetype.so.6"
  # Compare 8,064 grayscale/LCD glyph bitmaps per font against the original
  # library without the adapter, and validate the pinned private ABI prefixes.
  for variant in reference adapter; do
    flags=""
    libs="$out/lib/libfreetype-quantal.so.6"
    if test "$variant" = adapter; then
      flags="-DADAPTER -fsanitize=address,undefined ${./terminal-freetype.c}"
    fi
    $CC -Wall -Wextra -Werror -O1 -g $flags -I${freetype.dev}/include/freetype2 \
      ${./terminal-freetype-test.c} -Wl,-rpath,"$out/lib" $libs -o "$variant"
    ./$variant ${runtime}/usr/share/fonts/truetype/ubuntu-font-family/Ubuntu{-R,-B,-RI,Mono-R}.ttf > "$variant.hashes"
  done
  cmp reference.hashes adapter.hashes
''
