{ lib, stdenvNoCC, fetchurl, runCommand, python3, libarchive, squashfsTools
, bubblewrap, glibc, stdenv, libglvnd, libX11, libxcb, libdrm, zlib, expat
, libXext, libXdamage, libXrandr, libXrender, libXcomposite
, libXinerama, libXcursor, libXi, libxshmfence
, dbus, dconf, gvfs, cinnamon, cinnamon-session, cinnamon-screensaver, cinnamon-settings-daemon, polkit_gnome
, networkmanagerapplet, xdg-terminal-exec, xdg-utils, coreutils, bash, glib
, symlinkJoin, findutils, gnugrep, xorg-server, xprop, xwininfo, xdpyinfo
, xmessage, weston, xwayland, mesa-demos, xinput, xrandr, librsvg, imagemagick
}:
let
  iso = fetchurl {
    url = "https://old-releases.ubuntu.com/releases/12.10/ubuntu-12.10-desktop-amd64.iso";
    sha256 = "256a2cc652ec86ff366907fd7b878e577b631cc6c6533368c615913296069d80";
  };
  runtime = runCommand "unity-12.10-original-runtime" {
    nativeBuildInputs = [ python3 libarchive squashfsTools ];
  } ''
    bsdtar -xf ${iso} casper/filesystem.squashfs
    unsquashfs -no-progress -no-xattrs -excludes -d original casper/filesystem.squashfs dev
    mkdir -p "$out"
    python ${./assemble.py} original "$out"
  '';
  modernLibraries = lib.makeLibraryPath [
    glibc stdenv.cc.cc.lib libglvnd libX11 libxcb libdrm zlib expat
    # Unity 6.8 needs Ubuntu's XFixesSelectBarrierInput ABI. Retain its original
    # libXfixes while updating the GL loader and the DRI-capable X11 libraries.
    libXext libXdamage libXrandr libXrender libXcomposite
    libXinerama libXcursor libXi libxshmfence
  ];
in
stdenvNoCC.mkDerivation {
  pname = "unity-quantal-session";
  version = "6.8.0";
  src = ./.;
  nativeBuildInputs = [ python3 ];
  dontBuild = true;
  installPhase = ''
    mkdir -p "$out/bin" "$out/libexec/unity-quantal" "$out/share/xsessions"
    cp session.py bridge.py screensaver.py integration.py "$out/libexec/unity-quantal/"
    cat > "$out/libexec/unity-quantal/config.json" <<EOF
    ${builtins.toJSON {
      inherit runtime modernLibraries;
      loader = "${glibc}/lib/ld-linux-x86-64.so.2";
      bwrap = "${bubblewrap}/bin/bwrap";
      python = "${python3}/bin/python3";
      bridgePython = "${python3.withPackages (ps: [ ps.pygobject3 ])}/bin/python3";
      typelibs = "${glib}/lib/girepository-1.0";
      bash = "${bash}/bin/bash";
      dbus = "${dbus}/bin/dbus-daemon";
      dconfServices = "${dconf}/share/dbus-1/services";
      vfsServices = "${gvfs}/share/dbus-1/services";
      lockerServices = "${cinnamon-screensaver}/share/dbus-1/services";
      xinput = "${xinput}/bin/xinput";
      xrandr = "${xrandr}/bin/xrandr";
      rsvg = "${librsvg}/bin/rsvg-convert";
      gdbus = "${glib.bin}/bin/gdbus";
      xprop = "${xprop}/bin/xprop";
      session = "${cinnamon-session}/bin/cinnamon-session";
      sessionData = "${cinnamon}/share/gsettings-schemas/${cinnamon.name}";
      sessionQuit = "${cinnamon-session}/bin/cinnamon-session-quit";
      screensaver = "${cinnamon-screensaver}/bin/cinnamon-screensaver";
      screensaverCommand = "${cinnamon-screensaver}/bin/cinnamon-screensaver-command";
      polkit = "${polkit_gnome}/libexec/polkit-gnome-authentication-agent-1";
      network = "${networkmanagerapplet}/bin/nm-applet";
      mediaKeys = "${cinnamon-settings-daemon}/libexec/csd-media-keys";
      power = "${cinnamon-settings-daemon}/libexec/csd-power";
      terminal = "${xdg-terminal-exec}/bin/xdg-terminal-exec";
      open = "${xdg-utils}/bin/xdg-open";
      hostPath = lib.makeBinPath [ coreutils bash xdg-utils xdg-terminal-exec cinnamon-screensaver cinnamon-session ];
    }}
    EOF
    printf 'user-db:unity_quantal\n' > "$out/libexec/unity-quantal/dconf-profile"
    for command in session runtime refresh mouse; do
      cat > "$out/bin/unity-quantal-$command" <<EOF
    #!${bash}/bin/bash
    exec ${python3}/bin/python3 "$out/libexec/unity-quantal/session.py" $command "\$@"
    EOF
      chmod +x "$out/bin/unity-quantal-$command"
    done
    cat > "$out/share/xsessions/unity-quantal.desktop" <<EOF
    [Desktop Entry]
    Name=Unity 12.10
    Comment=Original Ubuntu 12.10 Unity on modern X11
    Exec=$out/bin/unity-quantal-session
    Type=Application
    DesktopNames=Unity;
    EOF
  '';
  passthru = {
    inherit runtime;
    testTools = symlinkJoin {
      name = "unity-quantal-test-tools";
      paths = [ bash coreutils findutils gnugrep bubblewrap xorg-server xprop
        xwininfo xdpyinfo xmessage glib dbus weston xwayland mesa-demos imagemagick ];
    };
    providedSessions = [ "unity-quantal" ];
  };
  meta = {
    description = "Original Unity 6.8 desktop with a current X11 session manager";
    platforms = [ "x86_64-linux" ];
    license = lib.licenses.gpl3Plus;
  };
}
