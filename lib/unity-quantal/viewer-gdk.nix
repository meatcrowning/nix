# Rebuild the original GDK ABI so internal calls receive the Cairo fix too.
{ stdenv, fetchurl, pkg-config, perl, python3, glib, atk, pango, cairo, gdk-pixbuf
, libX11, libXext, libXi, libXrandr, libXrender, libXfixes, libXcursor
, libXcomposite, libXdamage, libXinerama }:
stdenv.mkDerivation {
  pname = "unity-viewer-gdk";
  version = "3.6.0";
  src = fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/main/g/gtk+3.0/gtk+3.0_3.6.0.orig.tar.xz";
    sha256 = "e13f45225a795ebe9e4047486fa57b3232e6a21539983775db6cd4ae9046b049";
  };
  ubuntu = fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/main/g/gtk+3.0/gtk+3.0_3.6.0-0ubuntu3.debian.tar.gz";
    sha256 = "38fbcaf7c4ebdb2fec829fefc3a2d8598362b961861d4bf4c26a66e342b31077";
  };
  nativeBuildInputs = [ pkg-config perl python3 ];
  buildInputs = [ glib atk pango cairo gdk-pixbuf libX11 libXext libXi libXrandr
    libXrender libXfixes libXcursor libXcomposite libXdamage libXinerama ];
  postPatch = ''
    tar xf "$ubuntu"
    while read -r patch; do
      case "$patch" in ""|\#*) continue;; esac
      patch -p1 < "debian/patches/$patch"
    done < debian/patches/series
    python - <<'PY'
    from pathlib import Path
    p = Path('gdk/gdkcairo.c')
    s = p.read_text()
    start = s.index('void\ngdk_cairo_set_source_pixbuf (')
    end = s.index('\n}', start) + 2
    replacement = Path('${./viewer-cairo.c}').read_text()
    replacement = replacement[replacement.index('void gdk_cairo_set_source_pixbuf'):]
    p.write_text(s[:start] + replacement + s[end:])
    p = Path('gdk/gdkapplaunchcontext.c')
    s = p.read_text().replace('static void\ngdk_app_launch_context_init (',
        Path('${./viewer-launch-context.c}').read_text() + '\nstatic void\ngdk_app_launch_context_init (')
    s = s.replace('  context->workspace = -1;',
        '  context->workspace = -1;\n  viewer_restore_launch_environment(G_APP_LAUNCH_CONTEXT(context));')
    p.write_text(s)
    PY
  '';
  configureFlags = [ "--disable-introspection" "--disable-cups" "--disable-colord"
    "--disable-gtk-doc" "--disable-glibtest" "--disable-maintainer-mode"
    "--enable-x11-backend" "--disable-wayland-backend" "--disable-tests" ];
  env.NIX_CFLAGS_COMPILE = "-Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types";
  buildPhase = ''
    runHook preBuild
    make -C gdk -j$NIX_BUILD_CORES
    runHook postBuild
  '';
  installPhase = ''
    runHook preInstall
    make -C gdk install
    runHook postInstall
  '';
}
