{ stdenv, lib, pkg-config, libseccomp, glib, gdk-pixbuf, cairo, librsvg, bubblewrap, coreutils
, writeShellScript, writeText, closureInfo, runCommand, runtime, textStack }:
let
  renderer = stdenv.mkDerivation {
    name = "unity-svg-renderer";
    dontUnpack = true;
    nativeBuildInputs = [ pkg-config ];
    buildInputs = [ glib cairo librsvg libseccomp ];
    installPhase = ''
      mkdir -p "$out/bin"
      $CC -O2 -Wall -Wextra ${./viewer-svg-worker.c} $(pkg-config --cflags --libs librsvg-2.0 cairo) -lm -o "$out/bin/render"
      $CC -O2 -Wall -Wextra ${./restrict.c} -lseccomp -o "$out/bin/restrict"
    '';
  };
  closure = closureInfo { rootPaths = [ renderer fonts ]; };
  worker = writeShellScript "unity-svg-worker" ''
    unset LD_LIBRARY_PATH LD_PRELOAD
    bindings=()
    while IFS= read -r path; do bindings+=(--ro-bind "$path" "$path"); done < ${closure}/store-paths
    exec ${coreutils}/bin/timeout --kill-after=1s 15s ${bubblewrap}/bin/bwrap \
      --die-with-parent --new-session --unshare-all --unshare-user --disable-userns --cap-drop ALL \
      "''${bindings[@]}" --proc /proc --dev /dev --size 67108864 --tmpfs /tmp --remount-ro / --remount-ro /dev \
      --clearenv --setenv HOME /tmp --setenv LANG C.UTF-8 --setenv RAYON_NUM_THREADS 2 \
      --setenv FONTCONFIG_FILE ${fonts} \
      ${renderer}/bin/restrict ${renderer}/bin/render "$@"
  '';
  fonts = writeText "unity-svg-fonts.conf" ''
    <fontconfig><dir>${runtime}/usr/share/fonts</dir><cachedir>/tmp/fonts</cachedir></fontconfig>
  '';
in stdenv.mkDerivation {
  name = "unity-svg-bridge";
  dontUnpack = true;
  nativeBuildInputs = [ pkg-config ];
  buildInputs = [ glib gdk-pixbuf textStack ];
  installPhase = ''
    mkdir -p "$out/lib/pkgconfig" "$out/include/librsvg-2.0/librsvg"
    cp ${librsvg.dev}/include/librsvg-2.0/librsvg/*.h "$out/include/librsvg-2.0/librsvg/"
    $CC -O2 -Wall -Wextra -shared -fPIC -DSVG_WORKER='"${worker}"' \
      -Dgdk_cairo_set_source_pixbuf=viewer_svg_set_source_pixbuf ${./viewer-svg.c} ${./viewer-cairo.c} $(pkg-config --cflags --libs gio-2.0 gdk-pixbuf-2.0 cairo) -lm \
      -Wl,-soname,librsvg-2.so.2 -o "$out/lib/librsvg-2.so.2"
    ln -s librsvg-2.so.2 "$out/lib/librsvg-2.so"
    $CC -O2 -Wall -Wextra -shared -fPIC ${./viewer-svg-loader.c} \
      -I"$out/include/librsvg-2.0" -L"$out/lib" -Wl,-rpath,"$out/lib" -lrsvg-2 \
      $(pkg-config --cflags --libs gio-2.0 gdk-pixbuf-2.0 cairo) \
      -o "$out/lib/libpixbufloader-svg.so"
    ${gdk-pixbuf.dev}/bin/gdk-pixbuf-query-loaders "$out/lib/libpixbufloader-svg.so" > "$out/lib/svg-loaders.cache"
    cat ${gdk-pixbuf}/${gdk-pixbuf.binaryDir}/loaders.cache "$out/lib/svg-loaders.cache" > "$out/lib/loaders.cache"
    cat > "$out/lib/pkgconfig/librsvg-2.0.pc" <<PC
    prefix=$out
    libdir=$out/lib
    includedir=$out/include
    Name: librsvg
    Description: isolated SVG renderer for historical GTK
    Version: 2.62.3
    Requires: gio-2.0 gdk-pixbuf-2.0 cairo
    Libs: -L$out/lib -lrsvg-2
    Cflags: -I$out/include/librsvg-2.0
    PC
    export QT_QPA_PLATFORM=offscreen
    source ${../../tools/lib/session-guard.sh}
    sg_require_offscreen
    $CC -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer \
      -I"$out/include/librsvg-2.0" -DSVG_WORKER='"${worker}"' \
      -Dgdk_cairo_set_source_pixbuf=viewer_svg_set_source_pixbuf \
      ${./viewer-svg.c} ${./viewer-cairo.c} ${./viewer-svg-test.c} \
      $(pkg-config --cflags --libs gio-2.0 gdk-pixbuf-2.0 cairo) -lm -o svg-test
    ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=1 ./svg-test
    $CC -DFAKE_WORKER ${./viewer-svg-protocol-test.c} -o fake-worker
    $CC -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer \
      -I"$out/include/librsvg-2.0" -DSVG_WORKER=\"$PWD/fake-worker\" \
      -Dgdk_cairo_set_source_pixbuf=viewer_svg_set_source_pixbuf \
      ${./viewer-svg.c} ${./viewer-cairo.c} ${./viewer-svg-protocol-test.c} \
      $(pkg-config --cflags --libs gio-2.0 gdk-pixbuf-2.0 cairo) -lm -o protocol-test
    ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=1 ./protocol-test
  '';
}
