{ lib, stdenvNoCC, fetchurl, runCommand, python3, libarchive, squashfsTools
, bubblewrap, glibc, stdenv, libglvnd, libX11, libxcb, libdrm, zlib, expat
, libXext, libXdamage, libXrandr, libXrender, libXcomposite
, libXinerama, libXcursor, libXi, libxshmfence
, dbus, dconf, gvfs, cinnamon, cinnamon-session, cinnamon-screensaver, cinnamon-settings-daemon, polkit_gnome
, networkmanagerapplet, xdg-terminal-exec, xdg-utils, coreutils, bash, glib
, symlinkJoin, findutils, gnugrep, gnused, xorg-server, xprop, xwininfo, xdpyinfo, xdotool
, xmessage, weston, xwayland, mesa-demos, xinput, xrandr, librsvg, imagemagick
, pavucontrol, system-config-printer
, cinnamon-desktop
, xpra, zenity, closureInfo, writeText
, libseccomp, gnutar, gzip, bzip2, xz, unzip, zip
}:
let
  iso = fetchurl {
    url = "https://old-releases.ubuntu.com/releases/12.10/ubuntu-12.10-desktop-amd64.iso";
    sha256 = "256a2cc652ec86ff366907fd7b878e577b631cc6c6533368c615913296069d80";
  };
  runtime = runCommand "unity-12.10-original-runtime" {
    nativeBuildInputs = [ (python3.withPackages (ps: [ ps.pillow ])) libarchive squashfsTools ];
  } ''
    bsdtar -xf ${iso} casper/filesystem.squashfs
    unsquashfs -no-progress -no-xattrs -excludes -d original casper/filesystem.squashfs dev
    mkdir -p "$out"
    python ${./assemble.py} original "$out"
    python ${./dark-theme.py} "$out/usr/share/themes/Ambiance" "$out/usr/share/themes/Ambiance-Dark" \
      --artwork "$out/usr/share/gnome-control-center/ui/UbuntuLogo.png" \
      --panel "$out/usr/lib/control-center-1/panels/libbackground.so"
  '';
  # The default for new profiles; Appearance settings choose it afterwards.
  gtkTheme = "Ambiance-Dark";
  modernLibraries = lib.makeLibraryPath [
    glibc stdenv.cc.cc.lib libglvnd libX11 libxcb libdrm zlib expat
    # Unity 6.8 needs Ubuntu's XFixesSelectBarrierInput ABI. Retain its original
    # libXfixes while updating the GL loader and the DRI-capable X11 libraries.
    libXext libXdamage libXrandr libXrender libXcomposite
    libXinerama libXcursor libXi libxshmfence
  ];
  # Quantal's final Archive Manager update fixes the ISO build's extraction
  # crashes. Keep the other original applications and GTK libraries intact.
  isolatedArchiveDeb = fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/main/f/file-roller/file-roller_3.6.1.1-0ubuntu1.2_amd64.deb";
    hash = "sha256-uHNnxJQ8bxdYnrDbVwdd4NFnHsSdeP/tQBk9Ut81XE4=";
  };
  isolatedArchive = runCommand "unity-isolated-file-roller-3.6.1.1" {
    nativeBuildInputs = [ libarchive ];
  } ''
    mkdir -p "$out"
    bsdtar -xOf ${isolatedArchiveDeb} data.tar.gz | bsdtar -xf - -C "$out"
  '';
  archivePath = lib.makeBinPath [ gnutar gzip bzip2 xz unzip zip ];
  restrict = runCommand "unity-isolated-restrict" {
    nativeBuildInputs = [ stdenv.cc ];
    buildInputs = [ libseccomp ];
  } ''
    mkdir -p "$out/bin"
    $CC -Wall -Wextra -Werror -O2 ${./restrict.c} -lseccomp -o "$out/bin/unity-isolated-restrict"
  '';
  isolatedClosure = closureInfo {
    rootPaths = [ runtime isolatedArchive xpra xorg-server glibc bash dbus python3
      restrict (writeText "unity-isolated-libraries" (modernLibraries + ":" + archivePath)) ];
  };
in
stdenvNoCC.mkDerivation {
  pname = "unity-quantal-session";
  version = "6.8.0";
  src = ./.;
  nativeBuildInputs = [ python3 ];
  dontBuild = true;
  installPhase = ''
    mkdir -p "$out/bin" "$out/libexec/unity-quantal" "$out/share/xsessions"
    cp session.py bridge.py screensaver.py integration.py isolated.py "$out/libexec/unity-quantal/"
    cat > "$out/libexec/unity-quantal/config.json" <<EOF
    ${builtins.toJSON {
      inherit runtime modernLibraries archivePath gtkTheme;
      isolatedArchive = "${isolatedArchive}/usr/bin/file-roller";
      isolatedClosure = "${isolatedClosure}/store-paths";
      xpra = "${xpra}/bin/xpra";
      xvfb = "${xorg-server}/bin/Xvfb";
      zenity = "${zenity}/bin/zenity";
      restrict = "${restrict}/bin/unity-isolated-restrict";
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
      settingsData = lib.concatStringsSep ":" (map (p: "${p}/share/gsettings-schemas/${p.name}") [
        cinnamon cinnamon-desktop cinnamon-settings-daemon
      ]);
      settingsCommands = {
        network = [ "${networkmanagerapplet}/bin/nm-connection-editor" ];
        sound = [ "${pavucontrol}/bin/pavucontrol" ];
        printers = [ "${system-config-printer}/bin/system-config-printer" ];
        power = [ "${cinnamon}/bin/cinnamon-settings" "power" ];
        screen = [ "${cinnamon}/bin/cinnamon-settings" "screensaver" ];
        datetime = [ "${cinnamon}/bin/cinnamon-settings" "calendar" ];
      };
      mediaKeys = "${cinnamon-settings-daemon}/libexec/csd-media-keys";
      power = "${cinnamon-settings-daemon}/libexec/csd-power";
      terminal = "${xdg-terminal-exec}/bin/xdg-terminal-exec";
      open = "${xdg-utils}/bin/xdg-open";
      hostPath = lib.makeBinPath [ coreutils bash xdg-utils xdg-terminal-exec cinnamon-screensaver cinnamon-session ];
    }}
    EOF
    printf 'user-db:unity_quantal\n' > "$out/libexec/unity-quantal/dconf-profile"
    for command in session runtime refresh mouse settings; do
      cat > "$out/bin/unity-quantal-$command" <<EOF
    #!${bash}/bin/bash
    exec ${python3}/bin/python3 "$out/libexec/unity-quantal/session.py" $command "\$@"
    EOF
      chmod +x "$out/bin/unity-quantal-$command"
    done
    cat > "$out/bin/unity-quantal-isolated" <<EOF
    #!${bash}/bin/bash
    exec ${python3}/bin/python3 "$out/libexec/unity-quantal/isolated.py" "\$@"
    EOF
    chmod +x "$out/bin/unity-quantal-isolated"
    python "$out/libexec/unity-quantal/isolated.py" install "$out"
    # ly reads its sessions directory only at startup; a stable Exec keeps a
    # long-running greeter from starting the package of an older generation.
    cat > "$out/share/xsessions/unity-quantal.desktop" <<EOF
    [Desktop Entry]
    Name=Unity 12.10
    Comment=Original Ubuntu 12.10 Unity on modern X11
    Exec=/run/current-system/sw/bin/unity-quantal-session
    Type=Application
    DesktopNames=Unity;
    EOF
  '';
  passthru = {
    inherit runtime;
    testTools = symlinkJoin {
      name = "unity-quantal-test-tools";
      paths = [ bash coreutils findutils gnugrep gnused bubblewrap xorg-server xprop
        xwininfo xdpyinfo xdotool xmessage glib dbus weston xwayland mesa-demos imagemagick ];
    };
    providedSessions = [ "unity-quantal" ];
  };
  meta = {
    description = "Original Unity 6.8 desktop with a current X11 session manager";
    platforms = [ "x86_64-linux" ];
    license = lib.licenses.gpl3Plus;
  };
}
