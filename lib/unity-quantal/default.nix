{ lib, stdenvNoCC, fetchurl, runCommand, python3, libarchive, squashfsTools, callPackage
, bubblewrap, glibc, stdenv, libglvnd, libX11, libxcb, libdrm, zlib, expat
, libXext, libXdamage, libXrandr, libXrender, libXcomposite
, libXinerama, libXcursor, libXi, libxshmfence
, dbus, dconf, gvfs, cinnamon, cinnamon-session, cinnamon-screensaver, cinnamon-settings-daemon, polkit_gnome
, networkmanagerapplet, xdg-terminal-exec, xdg-utils, coreutils, bash, glib
, symlinkJoin, findutils, gnugrep, gnused, xorg-server, xprop, xwininfo, xdpyinfo, xdotool
, xmessage, xrdb, tab-window-manager, weston, xwayland, mesa-demos, xinput, xrandr, setxkbmap, librsvg, imagemagick
, pavucontrol, system-config-printer
, cinnamon-desktop
, xpra, zenity, closureInfo, writeText
, wrapGAppsHook3, gobject-introspection, gtk3, vte
, libseccomp, gnutar, gzip, bzip2, xz, unzip, zip
, gdk-pixbuf, ffmpegthumbnailer, ffmpeg-headless, writeShellScript
# The music library the original Rhythmbox reads, read-only, in its sandbox.
, musicLibrary
, libcanberra, libcanberra-gtk3, pulseaudio, patchelf
}:
let
  iso = fetchurl {
    url = "https://old-releases.ubuntu.com/releases/12.10/ubuntu-12.10-desktop-amd64.iso";
    sha256 = "256a2cc652ec86ff366907fd7b878e577b631cc6c6533368c615913296069d80";
  };
  # Quantal's own Nautilus extensions (Actions, Image Converter, Compare with
  # Meld) and the dependencies the ISO lacks, from the release archive.
  archivePackages = map fetchurl (lib.importJSON ./archive-packages.json);
  runtime = runCommand "unity-12.10-original-runtime" {
    nativeBuildInputs = [ (python3.withPackages (ps: [ ps.pillow ])) libarchive squashfsTools ];
  } ''
    bsdtar -xf ${iso} casper/filesystem.squashfs
    unsquashfs -no-progress -no-xattrs -excludes -d original casper/filesystem.squashfs dev
    mkdir -p "$out"
    python ${./assemble.py} original "$out" ${lib.concatStringsSep " " archivePackages}
    python ${./dark-theme.py} "$out/usr/share/themes/Ambiance" "$out/usr/share/themes/Ambiance-Dark" \
      --artwork "$out/usr/share/gnome-control-center/ui/UbuntuLogo.png" \
      --panel "$out/usr/lib/control-center-1/panels/libbackground.so"
  '';
  viewer = callPackage ./viewer.nix { inherit runtime legacyGtkModule; };
  # Ambiance Dark for current GTK 3 applications, whose CSS the 12.10 theme
  # predates: Ubuntu 18.04's port of Ambiance, under the same palette and name.
  nativeThemeDeb = fetchurl {
    url = "https://archive.ubuntu.com/ubuntu/pool/main/u/ubuntu-themes/light-themes_16.10+18.04.20181005-0ubuntu1_all.deb";
    hash = "sha256-P6IobhCcSkNJL7ephwQ7NBdSp/pI92hDRKXZmIuOPUM=";
  };
  nativeTheme = runCommand "unity-quantal-native-theme" {
    nativeBuildInputs = [ (python3.withPackages (ps: [ ps.pillow ])) libarchive ];
  } ''
    bsdtar -xOf ${nativeThemeDeb} data.tar.xz | bsdtar -xf - ./usr/share/themes/Ambiance
    rm -r usr/share/themes/Ambiance/{gtk-2.0,metacity-1,unity}
    mkdir -p "$out/share/themes"
    python ${./dark-theme.py} usr/share/themes/Ambiance "$out/share/themes/Ambiance-Dark" --native
  '';
  # The runtime's Ubuntu fonts, for the session font that XSETTINGS names.
  fonts = runCommand "unity-quantal-fonts" { } ''
    mkdir -p "$out/share/fonts/truetype"
    ln -s ${runtime}/usr/share/fonts/truetype/ubuntu-font-family "$out/share/fonts/truetype/"
  '';
  # Archive packages skip dpkg's schema trigger. The media sandbox compiles its
  # own copy; the session keeps the ISO's compiled schemas.
  mediaSchemas = runCommand "unity-quantal-media-schemas" {
    nativeBuildInputs = [ glib.dev ];
  } ''
    mkdir -p "$out"
    cp ${runtime}/usr/share/glib-2.0/schemas/*.xml ${runtime}/usr/share/glib-2.0/schemas/*.override "$out/"
    glib-compile-schemas "$out"
  '';
  legacyCanberra = libcanberra-gtk3.overrideAttrs (old: {
    postPatch = (old.postPatch or "") + ''
      # Keep X11 error traps on the window's own display. Ubuntu has no
      # generic window open/close/state samples; querying those windows from
      # an emission hook disrupts EOG's title updates through Xpra.
      substituteInPlace src/canberra-gtk-module.c \
        --replace-fail 'gdk_error_trap_push();' 'gdk_x11_display_error_trap_push(d);' \
        --replace-fail 'gdk_error_trap_pop_ignored();' 'gdk_x11_display_error_trap_pop_ignored(d);'
      substituteInPlace src/canberra-gtk-module.c \
        --replace-fail 'object = g_value_get_object(&param_values[0]);' \
          'object = g_value_get_object(&param_values[0]); if (GTK_IS_WINDOW(object) && !GTK_IS_DIALOG(object) && gtk_window_get_type_hint(GTK_WINDOW(object)) == GDK_WINDOW_TYPE_HINT_NORMAL) return TRUE;'
    '';
  });
  legacyGtkModule = runCommand "unity-quantal-gtk-sound-module" {
    nativeBuildInputs = [ patchelf ];
  } ''
    mkdir -p "$out/lib"
    cp ${legacyCanberra}/lib/gtk-3.0/modules/libcanberra-gtk3-module.so "$out/lib/"
    chmod u+w "$out/lib/libcanberra-gtk3-module.so"
    # A Nix RPATH would load current GTK/font libraries into a Quantal process.
    # The module's GTK 3 ABI works with 3.6; resolve its dependencies in FHS.
    patchelf --set-rpath /usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/usr/lib \
      "$out/lib/libcanberra-gtk3-module.so"
    # Current GTK's pkg-config adds HarfBuzz, but the module uses no hb_* API
    # and Quantal's Pango predates that dependency.
    patchelf --remove-needed libharfbuzz.so.0 "$out/lib/libcanberra-gtk3-module.so"
    patchelf --add-needed libcanberra-gtk3.so.0 "$out/lib/libcanberra-gtk3-module.so"
  '';
  # indicator-cpufreq's meter icons; its governor menu predates amd-pstate.
  cpufreqIconsDeb = fetchurl {
    url = "https://old-releases.ubuntu.com/ubuntu/pool/universe/i/indicator-cpufreq/indicator-cpufreq_0.1.4-0ubuntu2_all.deb";
    sha256 = "74f975533646a3d8133d124a99cecf1c83372996666ef80ce204f2eaf28764d0";
  };
  cpufreqIcons = runCommand "unity-quantal-cpufreq-icons" {
    nativeBuildInputs = [ libarchive ];
  } ''
    mkdir -p "$out"
    bsdtar -xOf ${cpufreqIconsDeb} data.tar.gz | bsdtar -xf - -C "$out" --strip-components 7 \
      ./usr/share/icons/ubuntu-mono-dark/status/22
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
  # Nautilus does not depend on thumbnail providers. Use current decoders,
  # without letting the Quantal process's library/loader overrides leak in.
  imageThumbnailer = writeShellScript "unity-image-thumbnailer" ''
    unset LD_LIBRARY_PATH GDK_PIXBUF_MODULE_FILE GDK_PIXBUF_MODULEDIR
    exec ${gdk-pixbuf}/bin/gdk-pixbuf-thumbnailer "$@"
  '';
  videoThumbnailer = writeShellScript "unity-video-thumbnailer" ''
    unset LD_LIBRARY_PATH GDK_PIXBUF_MODULE_FILE GDK_PIXBUF_MODULEDIR
    exec ${ffmpegthumbnailer}/bin/ffmpegthumbnailer "$@"
  '';
  thumbnailers = runCommand "unity-quantal-thumbnailers" { } ''
    mkdir -p "$out"
    cp ${gdk-pixbuf}/share/thumbnailers/gdk-pixbuf-thumbnailer.thumbnailer "$out/"
    cp ${ffmpegthumbnailer}/share/thumbnailers/ffmpegthumbnailer.thumbnailer "$out/"
    sed -i -E 's|^(TryExec=).*|\1${imageThumbnailer}|; s|^(Exec=)[^ ]+|\1${imageThumbnailer}|' \
      "$out/gdk-pixbuf-thumbnailer.thumbnailer"
    sed -i -E 's|^(TryExec=).*|\1${videoThumbnailer}|; s|^(Exec=)[^ ]+|\1${videoThumbnailer}|' \
      "$out/ffmpegthumbnailer.thumbnailer"
  '';
  terminalText = callPackage ./terminal-text.nix { inherit runtime; };
  # The session's terminal: GNOME Terminal 3.6's window over the current VTE.
  terminalApp = stdenvNoCC.mkDerivation {
    name = "unity-quantal-terminal-app";
    dontUnpack = true;
    nativeBuildInputs = [ wrapGAppsHook3 gobject-introspection ];
    buildInputs = [ gtk3 vte ];
    installPhase = ''
      mkdir -p "$out/bin"
      { echo "#!${python3.withPackages (ps: [ ps.pygobject3 ])}/bin/python3"; cat ${./terminal.py}; } > "$out/bin/unity-terminal"
      chmod +x "$out/bin/unity-terminal"
    '';
  };
  scrollGrab = runCommand "unity-quantal-scroll-grab" {
    nativeBuildInputs = [ stdenv.cc ];
    buildInputs = [ libX11 ];
  } ''
    mkdir -p "$out/lib"
    $CC -Wall -Wextra -Werror -shared -fPIC -O2 ${./scroll-grab.c} -lX11 -ldl -o "$out/lib/scroll-grab.so"
  '';
  restrict = runCommand "unity-isolated-restrict" {
    nativeBuildInputs = [ stdenv.cc ];
    buildInputs = [ libseccomp ];
  } ''
    mkdir -p "$out/bin"
    $CC -Wall -Wextra -Werror -O2 ${./restrict.c} -lseccomp -o "$out/bin/unity-isolated-restrict"
  '';
  isolatedClosure = closureInfo {
    rootPaths = [ runtime isolatedArchive mediaSchemas xpra xorg-server xrdb glibc bash dbus python3 legacyGtkModule
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
    cp session.py bridge.py screensaver.py integration.py isolated.py display.py cpufreq.py weather.py \
      mirror.py notifications.py sounds.py viewer-launch.py tweaks.json "$out/libexec/unity-quantal/"
    cp -r display-icons "$out/libexec/unity-quantal/"
    mkdir -p "$out/lib/gtk-3.0/modules"
    ln -s ${libcanberra-gtk3}/lib/gtk-3.0/modules/libcanberra-gtk3-module.so \
      "$out/lib/gtk-3.0/modules/libcanberra-gtk-module.so"
    # Quantal's cursors, for native applications that follow Xcursor.theme.
    mkdir -p "$out/share/icons"
    ln -s ${runtime}/usr/share/icons/DMZ-White ${runtime}/usr/share/icons/DMZ-Black "$out/share/icons/"
    ln -s ${nativeTheme}/share/themes "$out/share/themes"
    cat > "$out/libexec/unity-quantal/config.json" <<EOF
    ${builtins.toJSON {
      inherit runtime modernLibraries archivePath gtkTheme thumbnailers musicLibrary;
      viewer = "${viewer}/bin/unity-image-viewer";
      scrollGrab = "${scrollGrab}/lib/scroll-grab.so";
      isolatedArchive = "${isolatedArchive}/usr/bin/file-roller";
      mediaSchemas = "${mediaSchemas}";
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
      dconfModules = "${lib.getLib dconf}/lib/gio/modules";
      vfsServices = "${gvfs}/share/dbus-1/services";
      lockerServices = "${cinnamon-screensaver}/share/dbus-1/services";
      xinput = "${xinput}/bin/xinput";
      xrandr = "${xrandr}/bin/xrandr";
      rsvg = "${librsvg}/bin/rsvg-convert";
      gdbus = "${glib.bin}/bin/gdbus";
      gsettings = "${glib.bin}/bin/gsettings";
      xrdb = "${xrdb}/bin/xrdb";
      xprop = "${xprop}/bin/xprop";
      libX11 = "${libX11}/lib/libX11.so.6";
      libcanberra = "${libcanberra}/lib/libcanberra.so.0";
      nativeGtkModules = "$out/lib/gtk-3.0/modules";
      # Use the patched GTK module with Quantal's libraries and ISO samples.
      legacyGtkModule = "${legacyGtkModule}/lib/libcanberra-gtk3-module.so";
      pactl = "${pulseaudio}/bin/pactl";
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
      mediaKeys = "$out/bin/unity-quantal-media-keys";
      power = "${cinnamon-settings-daemon}/libexec/csd-power";
      terminal = "$out/bin/unity-quantal-terminal";
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
    ln -s ${terminalText}/etc/fonts/fonts.conf "$out/libexec/unity-quantal/terminal-fonts.conf"
    cat > "$out/bin/unity-quantal-terminal" <<EOF
    #!${bash}/bin/bash
    export _UNITY_TERMINAL_PRELOAD=\''${LD_PRELOAD-}
    export LD_PRELOAD=${terminalText}/lib/libfreetype.so.6\''${LD_PRELOAD:+:\$LD_PRELOAD}
    export FONTCONFIG_FILE=$out/libexec/unity-quantal/terminal-fonts.conf
    # The session's fixed-width font setting, from Unity's own profile.
    export DCONF_PROFILE=$out/libexec/unity-quantal/dconf-profile
    export UNITY_QUANTAL_SCHEMAS=${runtime}/usr/share/glib-2.0/schemas
    # Ctrl+Alt+T starts it from the original runtime, whose environment has no
    # cursor search path; without one it cannot find the session's cursors.
    export XCURSOR_PATH=\''${XCURSOR_PATH:-\$HOME/.local/share/icons:\$HOME/.icons:/etc/profiles/per-user/\$USER/share/icons:/run/current-system/sw/share/icons}
    exec ${terminalApp}/bin/unity-terminal "\$@"
    EOF
    chmod +x "$out/bin/unity-quantal-terminal"
    # Ctrl+Alt+T runs the media-keys daemon's gnome-terminal. Only that daemon
    # sees this shim, so other desktops keep their own terminals.
    mkdir -p "$out/libexec/unity-quantal/terminal-shim"
    ln -s "$out/bin/unity-quantal-terminal" "$out/libexec/unity-quantal/terminal-shim/gnome-terminal"
    cat > "$out/bin/unity-quantal-media-keys" <<EOF
    #!${bash}/bin/bash
    PATH=$out/libexec/unity-quantal/terminal-shim:\$PATH exec ${cinnamon-settings-daemon}/libexec/csd-media-keys "\$@"
    EOF
    chmod +x "$out/bin/unity-quantal-media-keys"
    # Session components launch this through /run/current-system, so an
    # auto-restart or unity-quantal-refresh runs the rebuilt code.
    cat > "$out/bin/unity-quantal-display" <<EOF
    #!${bash}/bin/bash
    exec $out/bin/unity-quantal-runtime /usr/bin/python2.7 "$out/libexec/unity-quantal/display.py" "\$@"
    EOF
    chmod +x "$out/bin/unity-quantal-display"
    cat > "$out/bin/unity-quantal-cpufreq" <<EOF
    #!${bash}/bin/bash
    exec $out/bin/unity-quantal-runtime /usr/bin/python2.7 "$out/libexec/unity-quantal/cpufreq.py" ${cpufreqIcons}
    EOF
    cat > "$out/bin/unity-quantal-weather" <<EOF
    #!${bash}/bin/bash
    exec $out/bin/unity-quantal-runtime /usr/bin/python2.7 "$out/libexec/unity-quantal/weather.py" indicator
    EOF
    cat > "$out/bin/unity-quantal-settings-mirror" <<EOF
    #!${bash}/bin/bash
    exec ${python3.withPackages (ps: [ ps.pygobject3 ])}/bin/python3 "$out/libexec/unity-quantal/mirror.py" "\$@"
    EOF
    chmod +x "$out/bin/unity-quantal-cpufreq" "$out/bin/unity-quantal-weather" "$out/bin/unity-quantal-settings-mirror"
    cat > "$out/bin/unity-quantal-sounds" <<EOF
    #!${bash}/bin/bash
    exec ${python3.withPackages (ps: [ ps.pygobject3 ])}/bin/python3 "$out/libexec/unity-quantal/sounds.py" "\$@"
    EOF
    chmod +x "$out/bin/unity-quantal-sounds"
    cat > "$out/bin/unity-quantal-isolated" <<EOF
    #!${bash}/bin/bash
    exec ${python3}/bin/python3 "$out/libexec/unity-quantal/isolated.py" "\$@"
    EOF
    cat > "$out/bin/unity-quantal-viewer" <<EOF
    #!${bash}/bin/bash
    exec ${python3}/bin/python3 "$out/libexec/unity-quantal/viewer-launch.py" "\$@"
    EOF
    chmod +x "$out/bin/unity-quantal-viewer"
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
    inherit runtime fonts viewer;
    testTools = symlinkJoin {
      name = "unity-quantal-test-tools";
      paths = [ bash coreutils findutils gnugrep gnused bubblewrap xorg-server xprop
        xwininfo xdpyinfo xdotool xmessage tab-window-manager glib dbus weston xwayland mesa-demos imagemagick xrandr setxkbmap xrdb
        ffmpeg-headless pulseaudio ];
    };
    providedSessions = [ "unity-quantal" ];
  };
  meta = {
    description = "Original Unity 6.8 desktop with a current X11 session manager";
    platforms = [ "x86_64-linux" ];
    license = lib.licenses.gpl3Plus;
  };
}
