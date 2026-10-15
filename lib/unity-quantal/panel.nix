# Preserve the original panel service and libraries, adding music and user menus.
{ stdenv, fetchurl, runtime, pkg-config, glib, gtk3, atk, at-spi2-core
, libX11, libXi, python3, patchelf, libarchive }:
let
  libcDev = fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/main/e/eglibc/libc6-dev_2.15-0ubuntu20_amd64.deb";
    sha256 = "f2ff4ec4f4cb1c30b083638a996593d93677d09f05addd5eec6f2c73eb19f4b4";
  };
  indicatorSource = fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/main/libi/libindicator/libindicator_12.10.1.orig.tar.gz";
    sha256 = "b2d2e44c10313d5c9cd60db455d520f80b36dc39562df079a3f29495e8f9447f";
  };
in stdenv.mkDerivation {
  pname = "unity-quantal-panel";
  version = "6.8.0";
  src = fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/main/u/unity/unity_6.8.0.orig.tar.gz";
    sha256 = "7fc1dbad3c676044f302664264b4843377e47be350139cc63388eb2888a18ab1";
  };
  nativeBuildInputs = [ pkg-config python3 patchelf libarchive ];
  buildInputs = [ glib gtk3 atk at-spi2-core libX11 libXi ];
  dontConfigure = true;
  dontFixup = true;
  postPatch = ''
    tar xf ${indicatorSource}
    cp ${./now-playing.c} services/now-playing.c
    cp ${./now-playing.h} services/now-playing.h
    cp ${./user-menu.c} services/user-menu.c
    cp ${./user-menu.h} services/user-menu.h
    python ${./panel-patch.py}
  '';
  buildPhase = ''
    cd services
    glib-genmarshal panel-marshal.list --body --prefix=panel_marshal > panel-marshal.c
    glib-genmarshal panel-marshal.list --header --prefix=panel_marshal > panel-marshal.h
    mkdir abi crt
    bsdtar -xOf ${libcDev} data.tar.gz | bsdtar -xf - -C crt
    for name in gtk-3 gdk-3 atk-1.0 atk-bridge-2.0 gio-2.0 gobject-2.0 glib-2.0 gmodule-2.0 gdk_pixbuf-2.0 pango-1.0 pangocairo-1.0 cairo indicator3 X11 Xi; do
      original=$(find ${runtime}/usr/lib ${runtime}/lib -name "lib$name.so.*" -type f | head -1)
      test -n "$original"
      ln -s "$original" "abi/lib$name.so"
    done
    # Old startup objects and libc keep the executable runnable inside Quantal.
    # Headers come from the current SDK; link only APIs present in the old ABI.
    $CC -nostdlib -no-pie crt/usr/lib/x86_64-linux-gnu/crt1.o crt/usr/lib/x86_64-linux-gnu/crti.o -std=gnu11 -O2 -Wall -Wno-deprecated-declarations \
      -DGLIB_VERSION_MIN_REQUIRED=GLIB_VERSION_2_34 -DGLIB_VERSION_MAX_ALLOWED=GLIB_VERSION_2_34 \
      -DGDK_VERSION_MIN_REQUIRED=GDK_VERSION_3_6 -DGDK_VERSION_MAX_ALLOWED=GDK_VERSION_3_6 \
      -DGETTEXT_PACKAGE='"unity"' \
      -DINDICATORDIR='"/usr/lib/indicators3/7"' \
      -DINDICATORICONDIR='"/usr/share/libindicator/icons"' \
      -I. -I../libindicator-12.10.1 $(pkg-config --cflags gtk+-3.0 atk-bridge-2.0 x11 xi) \
      panel-*.c now-playing.c user-menu.c -o unity-panel-service \
      -Labi -Wl,-rpath-link,${runtime}/usr/lib/x86_64-linux-gnu:${runtime}/lib/x86_64-linux-gnu \
      -lgtk-3 -lgdk-3 -latk-1.0 -latk-bridge-2.0 -lgio-2.0 -lgobject-2.0 -lglib-2.0 \
      -lgmodule-2.0 -lgdk_pixbuf-2.0 -lpango-1.0 -lpangocairo-1.0 -lcairo -lindicator3 -lX11 -lXi \
      ${runtime}/lib/x86_64-linux-gnu/libm.so.6 ${runtime}/lib/x86_64-linux-gnu/libc.so.6 \
      crt/usr/lib/x86_64-linux-gnu/libc_nonshared.a -lgcc crt/usr/lib/x86_64-linux-gnu/crtn.o
    patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 \
      --set-rpath /usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/usr/lib unity-panel-service
  '';
  installPhase = ''
    mkdir -p "$out/bin"
    cp unity-panel-service "$out/bin/"
  '';
}
