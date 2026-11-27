# Plasma 6 on X11 for the S22 phone: Nix inside Termux's proot, drawn by Termux:X11.
# No NixOS here (locked bootloader, no systemd), so this env and launcher stand in
# for services.desktopManager.plasma6. Keep the package list close to that module.
{ pkgs }:
let
  kde = pkgs.kdePackages;

  fonts = with pkgs; [ noto-fonts noto-fonts-color-emoji hack-font ];
  fontsConf = pkgs.makeFontsConf { fontDirectories = fonts; };

  env = pkgs.buildEnv {
    name = "phone-plasma-env";
    ignoreCollisions = true;
    pathsToLink = [ "/bin" "/share" "/libexec" "/lib" "/etc" ];
    paths = (with kde; [
      qtsvg qtimageformats frameworkintegration kcoreaddons kded kfilemetadata
      kguiaddons kiconthemes kimageformats kio kio-extras kpackage kservice
      plasma-activities solid

      kwin-x11 kscreen libkscreen kactivitymanagerd kde-cli-tools kglobalacceld
      plasma-desktop plasma-workspace libplasma plasma-integration kdeplasma-addons

      breeze breeze-icons oxygen oxygen-icons qqc2-breeze-style qqc2-desktop-style
      systemsettings kcmutils kmenuedit kinfocenter

      konsole dolphin kate ark gwenview okular spectacle
    ]) ++ (with pkgs; [
      hicolor-icon-theme xdg-user-dirs dbus mesa mesa-demos
      xrdb xset xsetroot xprop setxkbmap
      bashInteractive coreutils findutils gnugrep gnused procps less which
    ]) ++ fonts;
  };

  mesa = pkgs.mesa;

  launcher = pkgs.writeShellScriptBin "phone-plasma" ''
    set -eu
    E=${env}
    export PATH="$E/bin:$E/libexec:$PATH"
    export DISPLAY="''${DISPLAY:-:0}"
    export XDG_RUNTIME_DIR=/tmp/runtime-$USER
    mkdir -p "$XDG_RUNTIME_DIR"
    chmod 700 "$XDG_RUNTIME_DIR"
    export XDG_DATA_DIRS="$HOME/.local/share:$E/share"
    export XDG_CONFIG_DIRS="$HOME/.config/kdedefaults:$E/etc/xdg"
    export QT_PLUGIN_PATH="$E/lib/qt-6/plugins"
    export QML_IMPORT_PATH="$E/lib/qt-6/qml" QML2_IMPORT_PATH="$E/lib/qt-6/qml"
    export NIXPKGS_QT6_QML_IMPORT_PATH="$E/lib/qt-6/qml"
    export KPACKAGE_DEP_RESOLVERS_PATH="${kde.frameworkintegration.out}/libexec/kf6/kpackagehandlers"
    export FONTCONFIG_FILE=${fontsConf}
    export XDG_CURRENT_DESKTOP=KDE XDG_SESSION_DESKTOP=KDE XDG_SESSION_TYPE=x11 KDE_FULL_SESSION=true
    export QT_QPA_PLATFORM=xcb
    export PULSE_SERVER=tcp:127.0.0.1:4713

    # GL without /run/opengl-driver: point glvnd straight at Mesa (llvmpipe for now).
    export LD_LIBRARY_PATH="${mesa}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export __EGL_VENDOR_LIBRARY_FILENAMES=${mesa}/share/glvnd/egl_vendor.d/50_mesa.json
    export __GLX_VENDOR_LIBRARY_NAME=mesa
    export LIBGL_DRIVERS_PATH=${mesa}/lib/dri GBM_BACKENDS_PATH=${mesa}/lib/gbm

    # No systemd user manager: Plasma must use its legacy startup path.
    mkdir -p "$HOME/.config"
    [ -e "$HOME/.config/startkderc" ] || printf '[General]\nsystemdBoot=false\n' > "$HOME/.config/startkderc"

    exec dbus-run-session --config-file=${pkgs.dbus}/share/dbus-1/session.conf -- startplasma-x11
  '';
in
pkgs.symlinkJoin { name = "phone-desktop"; paths = [ launcher env ]; }
