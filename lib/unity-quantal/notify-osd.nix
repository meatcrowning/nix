# Build the original Notify OSD against its runtime ABI.
{ stdenv, fetchurl, runtime, pkg-config, glib, gtk3, atk, at-spi2-core
, libX11, libwnck, dbus-glib, dbus, pixman, python3, patchelf, libarchive }:
let
  libcDev = fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/main/e/eglibc/libc6-dev_2.15-0ubuntu20_amd64.deb";
    sha256 = "f2ff4ec4f4cb1c30b083638a996593d93677d09f05addd5eec6f2c73eb19f4b4";
  };
in stdenv.mkDerivation {
  pname = "unity-quantal-notify-osd";
  version = "0.9.34";
  src = fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/main/n/notify-osd/notify-osd_0.9.34.orig.tar.gz";
    sha256 = "12080deeaa5e1e10b420117351c2bd5db3421b0d1efcab8ee8052c808c3aaa3c";
  };
  # Match the ISO's 0ubuntu5 build, including Ubuntu's tint and shadow fixes.
  patches = [ (fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/main/n/notify-osd/notify-osd_0.9.34-0ubuntu5.diff.gz";
    sha256 = "6dab3bd045210f60710974ddde7d2eb7f1d3c2889814275bda7ab2ff6bfaf212";
  }) ];
  nativeBuildInputs = [ pkg-config python3 patchelf libarchive dbus-glib ];
  buildInputs = [ glib gtk3 atk at-spi2-core libX11 libwnck dbus-glib dbus pixman ];
  dontConfigure = true;
  dontFixup = true;
  postPatch = ''
    cp ${./notification-interaction.c} src/notification-interaction.c
    python ${./notification-patch.py}
  '';
  buildPhase = ''
    echo '#define HAVE_WNCK_SHUTDOWN 1' > config.h
    dbus-binding-tool --prefix=stack --mode=glib-server --output=src/stack-glue.h src/notify-osd.xml
    mkdir abi crt
    bsdtar -xOf ${libcDev} data.tar.gz | bsdtar -xf - -C crt
    for name in gtk-3 gdk-3 atk-1.0 atk-bridge-2.0 gio-2.0 gobject-2.0 glib-2.0 gmodule-2.0 gthread-2.0 gdk_pixbuf-2.0 pango-1.0 pangocairo-1.0 cairo wnck-3 dbus-glib-1 dbus-1 pixman-1 X11; do
      original=$(find ${runtime}/usr/lib ${runtime}/lib -name "lib$name.so.*" -type f | head -1)
      test -n "$original"
      ln -s "$original" "abi/lib$name.so"
    done
    # Old startup objects and libc keep the executable runnable inside Quantal.
    # Headers come from the current SDK; link only APIs present in the old ABI.
    $CC -nostdlib -no-pie crt/usr/lib/x86_64-linux-gnu/crt1.o crt/usr/lib/x86_64-linux-gnu/crti.o -std=gnu11 -O2 -Wall -Wno-deprecated-declarations \
      -DGLIB_VERSION_MIN_REQUIRED=GLIB_VERSION_2_34 -DGLIB_VERSION_MAX_ALLOWED=GLIB_VERSION_2_34 \
      -DGDK_VERSION_MIN_REQUIRED=GDK_VERSION_3_6 -DGDK_VERSION_MAX_ALLOWED=GDK_VERSION_3_6 \
      -DWNCK_I_KNOW_THIS_IS_UNSTABLE -DDATADIR='"/usr/share"' \
      -I. -Isrc -Iegg $(pkg-config --cflags gtk+-3.0 libwnck-3.0 dbus-glib-1 pixman-1 x11) \
      $(find src -name '*.c' ! -name display.c ! -name notification-interaction.c) egg/egg-*.c -o notify-osd \
      -Labi -Wl,-rpath-link,${runtime}/usr/lib/x86_64-linux-gnu:${runtime}/lib/x86_64-linux-gnu \
      -lgtk-3 -lgdk-3 -latk-1.0 -latk-bridge-2.0 -lgio-2.0 -lgobject-2.0 -lglib-2.0 \
      -lgmodule-2.0 -lgthread-2.0 -lgdk_pixbuf-2.0 -lpango-1.0 -lpangocairo-1.0 -lcairo -lwnck-3 -ldbus-glib-1 -ldbus-1 -lpixman-1 -lX11 \
      ${runtime}/lib/x86_64-linux-gnu/libm.so.6 ${runtime}/lib/x86_64-linux-gnu/libc.so.6 \
      crt/usr/lib/x86_64-linux-gnu/libc_nonshared.a -lgcc crt/usr/lib/x86_64-linux-gnu/crtn.o
    patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 \
      --set-rpath /usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/usr/lib notify-osd
  '';
  installPhase = ''
    mkdir -p "$out/bin"
    cp notify-osd "$out/bin/"
  '';
}
