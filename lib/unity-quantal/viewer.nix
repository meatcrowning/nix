{ lib, stdenv, runCommand, fetchurl, libarchive, pkg-config, autoreconfHook
, gnome-common, gtk-doc, intltool, yelp-tools, itstool, libxslt, glib, gdk-pixbuf, atk, at-spi2-atk
, pango, cairo, fontconfig, harfbuzz, libX11, libXext, libXi, libXrandr, libXrender, libXfixes
, libXcursor, libXcomposite, libXdamage, libXinerama, libepoxy, libxkbfile, dbus
, libexif, lcms2, exempi, libjpeg, librsvg, libxml2, zlib
, gobject-introspection, shared-mime-info, gsettings-desktop-schemas
, python3, runtime, legacyGtkModule, makeWrapper, callPackage, dconf, libcanberra, libvorbis, libtool, cups
}:
let
  textStack = callPackage ./viewer-text.nix { inherit runtime; };
  svgBridge = callPackage ./viewer-svg.nix { inherit runtime textStack; };
  gdk = callPackage ./viewer-gdk.nix { pango = textStack; cairo = textStack; };
  supportLibraries = [ glib gdk-pixbuf atk at-spi2-atk textStack libcanberra libvorbis libtool cups libX11 libXext
    libXi libXrandr libXrender libXfixes libXcursor libXcomposite libXdamage libXinerama
    libxkbfile dbus gobject-introspection stdenv.cc.cc.lib ];
  ubuntu = name: hash: fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/main/${name}";
    sha256 = hash;
  };
  headers = [
    (ubuntu "g/gtk+3.0/libgtk-3-dev_3.6.0-0ubuntu3_amd64.deb" "74d6b8fda6d465af0866e4a95dc97e3bc6ffb75596232237fc3410a2fa76b259")
    (ubuntu "g/gnome-desktop3/libgnome-desktop-3-dev_3.6.0.1-0ubuntu2_amd64.deb" "c9e075e2c34f19ef46331c57e97d9d02511e14d52765f06201150a8de839f9ba")
    (ubuntu "libp/libpeas/libpeas-dev_1.4.0-2ubuntu3_amd64.deb" "42c419a4c3a388038f37d506dabefab1a19e2c5481295a5e9c55217dc48e0330")
    (ubuntu "libg/libgrip/libgrip-dev_0.3.5-0ubuntu1_amd64.deb" "837b99605f2d791dbc38f657b943e83696cc0237cd858fcd782e146faabe5655")
  ];
  # The original widgets and text stack are retained. Raster decoder dependencies
  # come from nixpkgs, never from the ISO's general library search directory.
  widgetAbi = runCommand "unity-viewer-widget-abi" {
    nativeBuildInputs = [ libarchive python3 ];
  } ''
    mkdir -p "$out/include" "$out/lib/pkgconfig" deb
    for archive in ${lib.concatStringsSep " " headers}; do
      member=$(bsdtar -tf "$archive" | sed -n '/^data.tar/p')
      bsdtar -xOf "$archive" "$member" | bsdtar -xf - -C deb
    done
    cp -r deb/usr/include/* "$out/include/"
    cp deb/usr/lib/pkgconfig/*.pc deb/usr/lib/x86_64-linux-gnu/pkgconfig/*.pc "$out/lib/pkgconfig/"
    cp ${runtime}/usr/share/pkgconfig/gnome-icon-theme.pc "$out/lib/pkgconfig/"
    for name in canberra-gtk3 gtk-3 gnome-desktop-3 peas-1.0 peas-gtk-1.0 grip geis grail frame colord; do
      original=$(find ${runtime}/usr/lib -name "lib$name.so.*" -type f | head -1)
      test -n "$original"
      cp "$original" "$out/lib/"
      chmod u+w "$out/lib/$(basename "$original")"
      patchelf --set-rpath "$out/lib:${lib.makeLibraryPath supportLibraries}" "$out/lib/$(basename "$original")"
      ln -s "$(basename "$original")" "$out/lib/lib$name.so"
      soname=$(patchelf --print-soname "$original")
      test "$soname" = "$(basename "$original")" || ln -s "$(basename "$original")" "$out/lib/$soname"
    done
    cp -P ${gdk}/lib/libgdk-3.so* "$out/lib/"
    sed -i -e "s|^prefix=/usr$|prefix=$out|" \
      -e "s|^libdir=/usr/lib/x86_64-linux-gnu$|libdir=$out/lib|" \
      "$out"/lib/pkgconfig/*.pc
    sed -i 's/@GIO_REQUIRED/2.28.0/' "$out/lib/pkgconfig/libpeas-1.0.pc"
    mkdir -p "$out/lib/gtk-3.0/3.0.0/theming-engines" "$out/lib/girepository-1.0"
    cp ${runtime}/usr/lib/gtk-3.0/3.0.0/theming-engines/libunico.so \
      "$out/lib/gtk-3.0/3.0.0/theming-engines/"
    chmod u+w "$out/lib/gtk-3.0/3.0.0/theming-engines/libunico.so"
    patchelf --set-rpath "$out/lib:${lib.makeLibraryPath supportLibraries}" \
      "$out/lib/gtk-3.0/3.0.0/theming-engines/libunico.so"
    mkdir -p "$out/lib/gtk-3.0/3.0.0/printbackends"
    for name in file cups lpr; do
      target="$out/lib/gtk-3.0/3.0.0/printbackends/libprintbackend-$name.so"
      cp ${runtime}/usr/lib/x86_64-linux-gnu/gtk-3.0/3.0.0/printbackends/libprintbackend-$name.so "$target"
      chmod u+w "$target"
      patchelf --set-rpath "$out/lib:${lib.makeLibraryPath supportLibraries}" "$target"
    done
    mkdir -p "$out/lib/gtk-3.0/modules"
    cp ${legacyGtkModule}/lib/libcanberra-gtk3-module.so "$out/lib/gtk-3.0/modules/"
    chmod u+w "$out/lib/gtk-3.0/modules/libcanberra-gtk3-module.so"
    patchelf --set-rpath "$out/lib:${lib.makeLibraryPath supportLibraries}" "$out/lib/gtk-3.0/modules/libcanberra-gtk3-module.so"
    for name in Gtk Gdk GdkX11 Peas PeasGtk; do
      cp ${runtime}/usr/lib/girepository-1.0/$name-*.typelib "$out/lib/girepository-1.0/"
    done
  '';
  ubuntuPatches = ubuntu "e/eog/eog_3.6.0-0ubuntu1.debian.tar.gz" "45eabdc4aba5029c1c5da37c9fb43e2641b81e8235dd7a76974edb06f0fc5913";
  metadataSource = fetchurl {
    url = "https://codeload.github.com/GNOME/eog/tar.gz/e2fdc72a3b1321d464ab5e3c16d16b2966149fcf";
    sha256 = "37a16489a034b666e23aa640e280b48132a530f777738a97115b68c722155a47";
  };
  resources = runCommand "unity-viewer-resources" {} ''
    mkdir -p "$out/share"
    for name in icons themes fonts mime sounds help; do
      test ! -d ${runtime}/usr/share/$name || ln -s ${runtime}/usr/share/$name "$out/share/$name"
    done
  '';
  imageLibraries = [ glib gdk-pixbuf libexif lcms2 exempi libjpeg svgBridge libxml2 zlib ];
in
stdenv.mkDerivation {
  pname = "unity-quantal-viewer";
  version = "3.6.0-modern";
  src = fetchurl {
    url = "https://download.gnome.org/sources/eog/3.6/eog-3.6.0.tar.xz";
    sha256 = "8f8e43a337a3fb7071c650078f2ef89567b4889527f300d053491e9185dbae6b";
  };
  nativeBuildInputs = [ pkg-config autoreconfHook gnome-common gtk-doc intltool yelp-tools itstool libxslt (python3.withPackages (ps: [ ps.pillow ])) makeWrapper ];
  buildInputs = imageLibraries ++ [ widgetAbi atk at-spi2-atk textStack libX11 libXext
    libXi libXrandr libXrender libXfixes libXcursor libXcomposite libXdamage libXinerama
    libepoxy libxkbfile dbus gobject-introspection shared-mime-info gsettings-desktop-schemas ];
  postPatch = ''
    tar xf ${ubuntuPatches}
    patch -p1 < debian/patches/02_grip_gestures.patch
    mkdir maintained
    tar xf ${metadataSource} -C maintained --strip-components=1
    cp maintained/src/eog-metadata-reader*.c maintained/src/eog-metadata-reader*.h src/
    patch -p1 < ${./viewer-metadata.patch}
    # EOG vendors jpegtran code separately from libjpeg. Update both sides.
    python - <<'PY2'
    from pathlib import Path
    p = Path('src/eog-window.c')
    s = p.read_text().replace('g_app_info_launch (app,\n\t\t\t   files,\n\t\t\t   NULL, NULL);',
        'GdkAppLaunchContext *ctx = gdk_display_get_app_launch_context (gdk_display_get_default ());\n'
        '\tg_app_info_launch (app, files, G_APP_LAUNCH_CONTEXT (ctx), NULL);\n\tg_object_unref (ctx);')
    assert 'GdkAppLaunchContext *ctx =' in s
    s = s.replace('"gnome-control-center background"',
                  '"unity-quantal-runtime /usr/bin/gnome-control-center background"')
    p.write_text(s)
    p = Path('src/eog-image.c')
    s = p.read_text().replace('entry->format == EXIF_FORMAT_LONG)', 'entry->format == EXIF_FORMAT_LONG && entry->size >= 4)')
    s = s.replace('entry->format == EXIF_FORMAT_SHORT)', 'entry->format == EXIF_FORMAT_SHORT && entry->size >= 2)')
    s = s.replace('if (entry != NULL) {\n\t\t\tpriv->orientation', 'if (entry != NULL && entry->size >= 2) {\n\t\t\tpriv->orientation')
    start = s.index('static gboolean\nprivate_timeout (')
    end = s.index('\n}', start) + 2
    s = s[:start] + Path('${./viewer-animation.c}').read_text() + s[end:]
    s = s.replace('priv->anim_iter = gdk_pixbuf_animation_get_iter (priv->anim,NULL);', 'g_object_ref (priv->anim);\n\t\t\tpriv->anim_iter = gdk_pixbuf_animation_get_iter (priv->anim,NULL);')
    s = s.replace('g_object_ref (priv->anim_iter);', '/* The image owns the iterator. */')
    s = s.replace('g_timeout_add (gdk_pixbuf_animation_iter_get_delay_time (priv->anim_iter), private_timeout, img);',
                  'g_timeout_add_full (G_PRIORITY_DEFAULT, MAX (10, gdk_pixbuf_animation_iter_get_delay_time (priv->anim_iter)), private_timeout, g_object_ref (img), g_object_unref);')
    # The final data_unref may destroy the image; check the invariant first.
    s = s.replace('g_object_unref (G_OBJECT (img));\n\n\tg_assert (img->priv->data_ref_count <= G_OBJECT (img)->ref_count);',
                  'g_assert (img->priv->data_ref_count < G_OBJECT (img)->ref_count);\n\tg_object_unref (G_OBJECT (img));')
    p.write_text(s)
    p = Path('src/eog-print-preview.c')
    s = p.read_text().replace('\tcreate_surface (preview);\n\n\treturn FALSE;',
        '\tif (gtk_widget_get_realized (GTK_WIDGET (preview)))\n\t\tcreate_surface (preview);\n\n\treturn FALSE;')
    p.write_text(s)
    PY2
    cp ${libjpeg.src}/src/{transupp.c,transupp.h,jpegint.h,jpegapicomp.h,jinclude.h} jpegutils/
    printf '#define INLINE inline\n' > jpegutils/jconfigint.h
    printf 'INCLUDES = $(EOG_CFLAGS)\nnoinst_LTLIBRARIES = libeog-jpegutils.la\nlibeog_jpegutils_la_SOURCES = transupp.c transupp.h jpegint.h\n' > jpegutils/Makefile.am
    substituteInPlace src/eog-image-jpeg.c \
      --replace-fail 'g_try_malloc (w * 3 * sizeof (guchar))' 'g_try_malloc_n (w, 3 * sizeof (guchar))' \
      --replace-fail 'i*rowstride + j*(rowstride/w)' '(gsize)i*rowstride + (gsize)j*gdk_pixbuf_get_n_channels (pixbuf)'
    substituteInPlace src/eog-transform.c \
      --replace-fail '<cairo/cairo.h>' '<cairo.h>' \
      --replace-fail 'sy * src_rowstride' '(gsize) sy * src_rowstride' \
      --replace-fail 'y * dest_rowstride' '(gsize) y * dest_rowstride'
    substituteInPlace src/eog-print-preview.c \
      --replace-fail 'g_malloc (height * cairo_stride)' 'g_malloc_n (height, cairo_stride)' \
      --replace-fail 'g_idle_add ((GSourceFunc) create_surface_when_idle, preview);' \
        'g_idle_add_full (G_PRIORITY_DEFAULT_IDLE, (GSourceFunc) create_surface_when_idle, g_object_ref (preview), g_object_unref);'
  '';
  configureFlags = [ "--disable-introspection" "--disable-gtk-doc" "--disable-maintainer-mode" "--enable-compile-warnings=no" ];
  env.NIX_CFLAGS_COMPILE = "-Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types";
  enableParallelBuilding = true;
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    export QT_QPA_PLATFORM=offscreen
    source ${../../tools/lib/session-guard.sh}
    sg_require_offscreen
    $CC -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer \
      -DHAVE_CONFIG_H -I. -Isrc ${./viewer-metadata-test.c} \
      src/eog-metadata-reader.c src/eog-metadata-reader-jpg.c \
      src/eog-metadata-reader-png.c src/eog-debug.c \
      $(pkg-config --cflags --libs glib-2.0 gobject-2.0 gtk+-3.0 libexif lcms2 exempi-2.0) \
      -lz -o metadata-test
    ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=1 ./metadata-test
    $CC -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer \
      ${./viewer-cairo.c} ${./viewer-cairo-test.c} \
      $(pkg-config --cflags --libs gdk-3.0 cairo gio-2.0) -o cairo-test
    ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=1 ./cairo-test
    mkdir fixtures
    python - <<'FIXTURES'
    from PIL import Image
    from pathlib import Path
    image = Image.new('RGB', (32, 16), (255, 0, 0))
    for ext, fmt in [('png','PNG'), ('jpeg','JPEG'), ('bmp','BMP'), ('tiff','TIFF'),
                     ('ico','ICO'), ('gif','GIF'), ('pnm','PPM'), ('tga','TGA')]:
        image.save('fixtures/input.' + ext, format=fmt, sizes=[(32,16)], bitmap_format='bmp')
    image.save('fixtures/animation.gif', save_all=True, append_images=[Image.new('RGB', (32,16), (0,255,0))], duration=120, loop=0)
    Path('fixtures/input.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="16"><rect width="32" height="16" fill="red"/></svg>')
    Path('fixtures/input.xpm').write_text('/* XPM */\nstatic char *x[] = {"32 16 1 1", "r c red",' + ','.join(['"' + 'r'*32 + '"']*16) + '};')
    FIXTURES
    cat >> src/Makefile <<'MAKE'
    .RECIPEPREFIX := >
    viewer-image-test: libeog.la
    >$(LINK) -DHAVE_CONFIG_H -I. -I.. $(EOG_CFLAGS) ${./viewer-image-test.c} $(eog_LDADD) $(LIBS)
    MAKE
    make -C src viewer-image-test
    GDK_PIXBUF_MODULE_FILE=${svgBridge}/lib/loaders.cache src/viewer-image-test "$PWD/fixtures"
    runHook postCheck
  '';
  postInstall = ''
    mkdir -p "$out/lib/eog/girepository-1.0" "$out/libexec"
    cp ${runtime}/usr/lib/eog/girepository-1.0/Eog-3.0.typelib "$out/lib/eog/girepository-1.0/"
    mkdir -p "$out/libexec/schemas"
    cp "$out/share/gsettings-schemas/unity-quantal-viewer-3.6.0-modern/glib-2.0/schemas/"*.xml "$out/libexec/schemas/"
    cp ${runtime}/usr/share/glib-2.0/schemas/org.gnome.desktop.{background,interface,lockdown}*.xml "$out/libexec/schemas/"
    cp ${runtime}/usr/share/glib-2.0/schemas/org.gnome.desktop.enums.xml "$out/libexec/schemas/"
    # Ubuntu changed the upstream sidebar default; preserve its EOG overrides.
    python - "$out/libexec/schemas/10_ubuntu-settings.gschema.override" <<'PY'
    import configparser, sys
    source = configparser.ConfigParser(interpolation=None)
    source.optionxform = str
    source.read('${runtime}/usr/share/glib-2.0/schemas/10_ubuntu-settings.gschema.override')
    result = configparser.ConfigParser(interpolation=None)
    result.optionxform = str
    for section in source.sections():
        if section.startswith('org.gnome.eog'):
            result[section] = source[section]
    with open(sys.argv[1], 'w') as stream:
        result.write(stream)
    PY
    ${glib.dev}/bin/glib-compile-schemas "$out/libexec/schemas"
    echo 'user-db:unity_quantal' > "$out/libexec/dconf-profile"
    mv "$out/bin/eog" "$out/libexec/eog"
    makeWrapper "$out/libexec/eog" "$out/bin/unity-image-viewer" \
      --run 'for key in LD_LIBRARY_PATH LD_PRELOAD GDK_PIXBUF_MODULEDIR GDK_PIXBUF_MODULE_FILE GTK_PATH GTK_DATA_PREFIX GTK_MODULES GTK_IM_MODULE GI_TYPELIB_PATH GSETTINGS_SCHEMA_DIR GIO_EXTRA_MODULES GIO_MODULE_DIR GIO_USE_VFS DCONF_PROFILE UBUNTU_MENUPROXY XDG_DATA_DIRS GSETTINGS_BACKEND GTK_THEME PANGO_RC_FILE FONTCONFIG_FILE FONTCONFIG_PATH; do if [[ -v "$key" ]]; then export "_UNITY_VIEWER_HOST_$key=set:''${!key}"; else export "_UNITY_VIEWER_HOST_$key=unset"; fi; done' \
      --unset LD_LIBRARY_PATH --unset GDK_PIXBUF_MODULEDIR \
      --unset LD_PRELOAD \
      --set GDK_PIXBUF_MODULE_FILE "${svgBridge}/lib/loaders.cache" \
      --set FONTCONFIG_PATH "${runtime}/etc/fonts" \
      --set FONTCONFIG_FILE "${textStack}/etc/fonts.conf" \
      --set PANGO_RC_FILE "${textStack}/etc/pango/pangorc" \
      --set GTK_PATH "${widgetAbi}/lib/gtk-3.0" \
      --set GTK_DATA_PREFIX "${runtime}/usr" \
      --set GTK_MODULES "${widgetAbi}/lib/gtk-3.0/modules/libcanberra-gtk3-module.so" --set GTK_IM_MODULE gtk-im-context-simple \
      --set GI_TYPELIB_PATH "$out/lib/eog/girepository-1.0:${widgetAbi}/lib/girepository-1.0:${lib.makeSearchPath "lib/girepository-1.0" (map lib.getLib [ glib gdk-pixbuf textStack atk gobject-introspection ])}" \
      --set GSETTINGS_SCHEMA_DIR "$out/libexec/schemas" \
      --set GIO_EXTRA_MODULES "${dconf.lib}/lib/gio/modules" \
      --set GIO_MODULE_DIR "${dconf.lib}/lib/gio/modules" \
      --set GIO_USE_VFS local --set DCONF_PROFILE "$out/libexec/dconf-profile" \
      --set UBUNTU_MENUPROXY 0 \
      --prefix XDG_DATA_DIRS : "${resources}/share" \
      --run 'unset GSETTINGS_BACKEND' \
      --run 'export GTK_THEME="''${GTK_THEME:-Ambiance-Dark}"'
    ln -s unity-image-viewer "$out/bin/eog"
  '';
  passthru = { inherit widgetAbi imageLibraries textStack svgBridge; };
  meta = {
    description = "Ubuntu 12.10 Image Viewer with maintained image processing";
    platforms = [ "x86_64-linux" ];
    license = lib.licenses.gpl2Plus;
  };
}
