{ config, pkgs, lib, host, ... }:

let
  # The active wallpaper is a basename, not a host path: wal-repo-sync.sh
  # versions the image beside this selector. Both machines seed that directory
  # at activation, so Plasma can use one durable choice without copying mutable
  # monitor ids between hosts. Update this selector when the shared wallpaper
  # choice changes; mutable containment files remain host-local.
  sharedWallpaperName = lib.removeSuffix "\n"
    (builtins.readFile ./srvs/wal-files/current-wallpaper);
  sharedWallpaper =
    "${config.home.homeDirectory}/Pictures/wall/${sharedWallpaperName}";
  plasmaManagerLogin = pkgs.writeShellScript "plasma-manager-login" ''
    export PATH=${lib.makeBinPath [ pkgs.kdePackages.qttools ]}:$PATH
    exec ${config.xdg.dataHome}/plasma-manager/run_all.sh
  '';

  # See the comment on `input.mice` below. Hoisted into a `let` so the
  # activation script that pushes the same values at a RUNNING KWin cannot
  # drift from the ones written into kcminputrc.
  mice = [
    {
      name = "Logitech ERGO M575";
      vendorId = "046d";
      productId = "4096";
      acceleration = -0.2;
      accelerationProfile = "none";
    }
    {
      name = "ERGO M575 Mouse";
      vendorId = "046d";
      productId = "b027";
      acceleration = -0.2;
      accelerationProfile = "none";
    }
  ];
in

{
  programs.plasma = {
    enable = true;

    # Both hosts: the "new Oxygen" KDE global theme (org.kde.oxygen — the
    # revived Oxygen look-and-feel bundled by kdePackages.oxygen, distinct
    # from the classic pre-Plasma-5 Oxygen). `plasma-apply-lookandfeel` pulls
    # in Oxygen's own colour scheme (OxygenDark), icons, cursor (Oxygen_Black)
    # and kwin decoration together, matching what its packaged defaults file
    # sets (oxygen-6.7.4/share/plasma/look-and-feel/org.kde.oxygen/contents/defaults).
    # soundTheme is separate — lookAndFeel doesn't touch Sounds.Theme. Applies
    # on next PLASMA login (programs.plasma.startup, overrideConfig=false
    # means it's a one-shot autostart script, not a live rewrite). Per
    # docs/DESIGN.md §"In a PLASMA session none of this applies": the apps'
    # colours already follow whatever KDE global theme is picked, so this is
    # just picking Oxygen as that theme rather than adding a new mechanism.
    # The colour scheme is a separate desktop-wide choice in
    # home/prog/plasma-colors.nix: both hosts use the brighter,
    # focus-invariant OxygenDarkFlat palette. The wallpaper, Plasma style and
    # look-and-feel are shared here too; monitor scale remains the host seam.
    # soundTheme is NOT declared [2026-08-29]: plasma-manager re-asserted it on
    # every Plasma login, so a pack picked in System Settings was silently put
    # back to oxygen at the next session start, with nothing saying why. His
    # call — the event sounds are a preference, not something a fresh machine
    # needs guaranteed. lookAndFeel stays, because the colour pipeline reads
    # the picked global theme (home/prog/plasma-colors.nix).
    workspace = {
      lookAndFeel = "org.kde.oxygen";
      theme = "oxygen-scheme";
      wallpaper = sharedWallpaper;
      wallpaperFillMode = "preserveAspectCrop";
    };

    # The type layout top is using. Plasma's mutable kdeglobals had drifted on
    # book (Breeze/Oxygen Mono 10), so applications on the two hosts were not
    # merely scaled differently: they were different faces. Screen scaling is
    # still host-specific below; the actual type choices are desktop-global.
    fonts = {
      general = { family = "Oxygen-Sans"; pointSize = 8; };
      fixedWidth = { family = "Oxygen Mono"; pointSize = 9; };
      small = { family = "Oxygen-Sans"; pointSize = 8; };
      toolbar = { family = "Oxygen-Sans"; pointSize = 8; };
      menu = { family = "Oxygen-Sans"; pointSize = 8; };
      windowTitle = { family = "Oxygen-Sans"; pointSize = 8; };
    };

    # One semantic panel layout, recreated without copying top's containment
    # ids, activity UUIDs or four-screen map to book. The panels live on the
    # primary output on either host; only the tray's hardware applets differ.
    panels = [
      {
        location = "top";
        height = 22;
        floating = false;
        opacity = "opaque";
        widgets = [
          {
            name = "org.kde.plasma.panelspacer";
            config.General = { expanding = false; length = 6; };
          }
          {
            name = "org.kde.plasma.kickoff";
            config.General = {
              icon = "launcher-circle";
              systemFavorites = "suspend,hibernate,reboot,shutdown";
            };
          }
          "org.kde.plasma.appmenu"
          "org.kde.lam.menubar"
          "org.kde.plasma.panelspacer"
          {
            name = "org.kde.plasma.digitalclock";
            config.Appearance = {
              autoFontAndSize = false;
              dateDisplayFormat = "BesideTime";
              dateFormat = "longDate";
              displayTimezoneFormat = "FullText";
              fontFamily = "Oxygen-Sans";
              # The deliberately compact clock text from the live panel. Keep
              # this in the shared layout so a panel migration/rebuild does
              # not restore the earlier 9-point setting on either host.
              fontSize = 6;
              fontStyleName = "Sans-Book";
              fontWeight = 400;
              use24hFormat = 0;
            };
          }
          "org.kde.plasma.panelspacer"
          {
            name = "org.kde.plasma.weather";
            config.WeatherStation = {
              placeDisplayName = "Juneau, Juneau International Airport, AK";
              placeInfo = "Juneau, Juneau International Airport, AK";
              provider = "noaa";
            };
          }
          "org.kde.plasma.mediacontroller"
          {
            name = "org.kde.plasma.systemtray";
            config.General = {
              disabledStatusNotifiers = "fooyin,udiskie,.openrgb-wrapped";
              extraItems = lib.concatStringsSep "," ([
                "org.kde.kdeconnect"
                "org.kde.plasma.clipboard"
                "org.kde.plasma.manage-inputmethod"
                "org.kde.plasma.notifications"
                "org.kde.plasma.cameraindicator"
                "org.kde.plasma.networkmanagement"
                "org.kde.plasma.keyboardlayout"
                "org.kde.plasma.keyboardindicator"
                "org.kde.plasma.printmanager"
                "org.kde.plasma.volume"
                "org.kde.kscreen"
                "org.kde.plasma.brightness"
                "org.kde.plasma.weather"
              ] ++ lib.optionals (host == "air") [
                "org.kde.plasma.devicenotifier"
                "org.kde.plasma.bluetooth"
                "org.kde.plasma.battery"
              ]);
              iconSpacing = 1;
              shownItems = "Easy Effects";
            };
          }
          "org.kde.lam.notifgap"
          "org.kde.lam.playervisualizer"
        ];
      }
      {
        location = "left";
        height = 42;
        floating = false;
        opacity = "opaque";
        widgets = [
          {
            name = "org.kde.plasma.icontasks";
            config.General = {
              forceStripes = true;
              launchers = "applications:systemsettings.desktop,preferred://filemanager,preferred://browser,applications:painter.desktop,applications:player.desktop,applications:oracle.desktop";
              maxStripes = 1;
            };
          }
          "org.kde.plasma.panelspacer"
          "org.kde.plasma.marginsseparator"
          {
            # This is the upper of the two Folder View buttons at the bottom
            # of the left panel. `folder-games` is supplied by Oxygen itself,
            # so its palette/contrast variants continue to come from the
            # active Oxygen icon theme rather than from a hard-coded asset.
            name = "org.kde.plasma.folder";
            config.General = {
              useCustomIcon = true;
              icon = "folder-games";
              url = "file://${config.xdg.dataHome}/plasma-games";
              labelMode = 3;
              labelText = "games";
              sortMode = 1;
            };
          }
          "org.kde.plasma.folder"
          "org.kde.plasma.trash"
        ];
      }
    ];

    # The Logitech ERGO M575 trackball, so a PLASMA session on either host
    # feels like the Hyprland one. Hyprland gets sensitivity -0.200 +
    # accel_profile "flat" from the `hl.device` rules in
    # home/prog/hypr-files/hyprland.lua; these are the same two numbers for
    # KWin. `accelerationProfile = "none"` is plasma-manager's name for
    # PointerAccelerationProfile=1, which is libinput's FLAT — not "no
    # acceleration".
    #
    # TWO entries because the same trackball reports a different name and
    # product id per transport, and both KWin and Hyprland match on those:
    # over its USB receiver it is `Logitech ERGO M575` / 046d:4096, over
    # bluetooth `ERGO M575 Mouse` / 046d:b027. `top` had only the receiver
    # entry (hand-written years ago by the KCM) and `book` had neither, which
    # is why the bluetooth trackball on book ran on KDE's adaptive default.
    # A section for a transport that is not plugged in is inert, so both
    # hosts carry both.
    # NOTE: writing kcminputrc is only half of it. A RUNNING KWin does not
    # re-read a device's libinput settings when the file changes — it reads
    # them once, when the device is added — so the block below reaches the
    # session at the NEXT login and no sooner. That is how the first attempt
    # at this looked like it had worked and had not: kcminputrc said flat
    # /-0.200 while KWin's own
    # `/org/kde/KWin/InputDevice/eventN org.kde.KWin.InputDevice` properties
    # still said adaptive/0. `kwinReconfigure` below pushes the same two
    # values over that D-Bus interface (exactly what the KCM does) so a switch
    # applies immediately, and is a silent no-op when KWin is not on the bus.
    input.mice = mice;

    shortcuts = {
      "KDE Keyboard Layout Switcher"."Switch to Last-Used Keyboard Layout" = "Meta+Alt+L";
      "KDE Keyboard Layout Switcher"."Switch to Next Keyboard Layout" = "Meta+Alt+K";
      kaccess."Toggle Screen Reader On and Off" = "Meta+Alt+S";
      kmix.decrease_microphone_volume = "Microphone Volume Down";
      kmix.decrease_volume = "Volume Down";
      kmix.decrease_volume_small = "Shift+Volume Down";
      kmix.increase_microphone_volume = "Microphone Volume Up";
      kmix.increase_volume = "Volume Up";
      kmix.increase_volume_small = "Shift+Volume Up";
      kmix.mic_mute = ["Microphone Mute" "Meta+Volume Mute"];
      kmix.mute = "Volume Mute";
      ksmserver."Lock Session" = ["Meta+L" "Screensaver"];
      ksmserver."Log Out" = "Ctrl+Alt+Del";
      kwin."Activate Window Demanding Attention" = "Meta+Ctrl+A";
      kwin."Edit Tiles" = "Meta+T";
      kwin.Expose = "Ctrl+F9";
      kwin.ExposeAll = ["Ctrl+F10" "Launch (C)"];
      kwin.ExposeClass = "Ctrl+F7";
      kwin."Grid View" = "Meta+G";
      kwin."Kill Window" = "Meta+Ctrl+Esc";
      kwin.MoveMouseToCenter = "Meta+F6";
      kwin.MoveMouseToFocus = "Meta+F5";
      kwin.Overview = "Meta+W";
      kwin."Show Desktop" = "Meta+D";
      kwin."Switch One Desktop Down" = "Meta+Ctrl+Down";
      kwin."Switch One Desktop Up" = "Meta+Ctrl+Up";
      kwin."Switch One Desktop to the Left" = "Meta+Ctrl+Left";
      kwin."Switch One Desktop to the Right" = "Meta+Ctrl+Right";
      kwin."Switch Window Down" = "Meta+Alt+Down";
      kwin."Switch Window Left" = "Meta+Alt+Left";
      kwin."Switch Window Right" = "Meta+Alt+Right";
      kwin."Switch Window Up" = "Meta+Alt+Up";
      kwin."Switch to Desktop 1" = "Ctrl+F1";
      kwin."Switch to Desktop 2" = "Ctrl+F2";
      kwin."Switch to Desktop 3" = "Ctrl+F3";
      kwin."Switch to Desktop 4" = "Ctrl+F4";
      kwin."Walk Through Windows" = ["Meta+Tab" "Alt+Tab"];
      kwin."Walk Through Windows (Reverse)" = ["Meta+Shift+Tab" "Alt+Shift+Tab"];
      kwin."Walk Through Windows of Current Application" = ["Meta+`" "Alt+`"];
      kwin."Walk Through Windows of Current Application (Reverse)" = ["Meta+~" "Alt+~"];
      kwin."Window Close" = "Alt+F4";
      kwin."Window Fullscreen" = "Meta+F";
      kwin."Window Maximize" = "Meta+PgUp";
      kwin."Window Minimize" = "Meta+PgDown";
      kwin."Window One Desktop Down" = "Meta+Ctrl+Shift+Down";
      kwin."Window One Desktop Up" = "Meta+Ctrl+Shift+Up";
      kwin."Window One Desktop to the Left" = "Meta+Ctrl+Shift+Left";
      kwin."Window One Desktop to the Right" = "Meta+Ctrl+Shift+Right";
      kwin."Window Operations Menu" = "Alt+F3";
      kwin."Window Quick Tile Bottom" = "Meta+Down";
      kwin."Window Quick Tile Left" = "Meta+Left";
      kwin."Window Quick Tile Right" = "Meta+Right";
      # The rollupwindow KWin script (home/prog/kwin-rollup.nix). Meta+R, which
      # matches hyprvtb's rollup in the Hyprland session, is a recording hotkey
      # here, so the roll goes on the key that says what it does.
      kwin.RollUpWindow = "Meta+Shift+Up";
      kwin."Window Quick Tile Top" = "Meta+Up";
      kwin."Window to Next Screen" = "Meta+Shift+Right";
      kwin."Window to Previous Screen" = "Meta+Shift+Left";
      kwin.disableInputCapture = "Meta+Shift+Esc";
      kwin.view_actual_size = "Meta+0";
      kwin.view_zoom_in = ["Meta++" "Meta+="];
      kwin.view_zoom_out = "Meta+-";
      mediacontrol.nextmedia = "Media Next";
      mediacontrol.pausemedia = "Media Pause";
      mediacontrol.playpausemedia = "Media Play";
      mediacontrol.previousmedia = "Media Previous";
      mediacontrol.stopmedia = "Media Stop";
      org_kde_powerdevil."Decrease Keyboard Brightness" = "Keyboard Brightness Down";
      # PowerDevil has no config key for the brightness step size — the plain
      # actions compute ~20 steps across the hardware range in C++
      # (ScreenBrightnessLogic::calculateSteps), while "...Small" is hardcoded
      # to exactly 1%. So the physical keys are bound to the Small action to
      # get a 1% step, and the coarse step moves to Shift+ instead.
      org_kde_powerdevil."Decrease Screen Brightness" = "Shift+Monitor Brightness Down";
      org_kde_powerdevil."Decrease Screen Brightness Small" = "Monitor Brightness Down";
      org_kde_powerdevil.Hibernate = "Hibernate";
      org_kde_powerdevil."Increase Keyboard Brightness" = "Keyboard Brightness Up";
      org_kde_powerdevil."Increase Screen Brightness" = "Shift+Monitor Brightness Up";
      org_kde_powerdevil."Increase Screen Brightness Small" = "Monitor Brightness Up";
      org_kde_powerdevil.PowerDown = "Power Down";
      org_kde_powerdevil.PowerOff = "Power Off";
      org_kde_powerdevil.Sleep = "Sleep";
      org_kde_powerdevil."Toggle Keyboard Backlight" = "Keyboard Light On/Off";
      org_kde_powerdevil.powerProfile = ["Battery" "Meta+B"];
      plasmashell."activate application launcher" = ["Meta" "Alt+F1"];
      plasmashell."activate task manager entry 1" = "Meta+1";
      plasmashell."activate task manager entry 2" = "Meta+2";
      plasmashell."activate task manager entry 3" = "Meta+3";
      plasmashell."activate task manager entry 4" = "Meta+4";
      plasmashell."activate task manager entry 5" = "Meta+5";
      plasmashell."activate task manager entry 6" = "Meta+6";
      plasmashell."activate task manager entry 7" = "Meta+7";
      plasmashell."activate task manager entry 8" = "Meta+8";
      plasmashell."activate task manager entry 9" = "Meta+9";
      plasmashell.clipboard_action = "Meta+Ctrl+X";
      plasmashell.cycle-panels = "Meta+Alt+P";
      plasmashell."manage activities" = "Meta+Q";
      plasmashell."next activity" = "Meta+A";
      plasmashell."previous activity" = "Meta+Shift+A";
      plasmashell."show dashboard" = "Ctrl+F12";
      plasmashell.show-on-mouse-pos = "Meta+V";
    };

    configFile = {
      dolphinrc.General.EditableUrl = true;
      dolphinrc.General.ShowFullPath = true;
      dolphinrc.General.ShowStatusBar = "FullWidth";
      dolphinrc.General.ShowZoomSlider = true;
      dolphinrc."KFileDialog Settings"."Places Icons Auto-resize" = false;
      dolphinrc."KFileDialog Settings"."Places Icons Static Size" = 22;
      # Konsole's clean window is a desktop preference, not an accidental
      # property of top's KConfig state.  Its root-level MenuBar key cannot be
      # expressed by plasma-manager's section-only KConfig schema, so the
      # launcher below is the durable authority for each new window.
      konsolerc.MainWindow.ToolBarsMovable = "Enabled";
      katerc.General."Days Meta Infos" = 30;
      katerc.General."Save Meta Infos" = true;
      katerc.General."Show Full Path in Title" = false;
      katerc.General."Show Menu Bar" = true;
      katerc.General."Show Status Bar" = true;
      katerc.General."Show Tab Bar" = true;
      katerc.General."Show Url Nav Bar" = true;
      katerc.filetree.editShade = "183,220,246";
      katerc.filetree.listMode = false;
      katerc.filetree.shadingEnabled = true;
      katerc.filetree.showToolbar = true;
      katerc.filetree.viewShade = "211,190,222";
      kded5rc.Module-device_automounter.autoload = false;
      kdeglobals."KFileDialog Settings"."Automatically select filename extension" = true;
      kdeglobals."KFileDialog Settings"."Breadcrumb Navigation" = true;
      kdeglobals."KFileDialog Settings"."Show Inline Previews" = true;
      kdeglobals."KFileDialog Settings"."Sort by" = "Name";
      kdeglobals."KFileDialog Settings"."Sort directories first" = true;
      # Plasma visuals are shared. The live icon theme is intentionally not
      # pinned: wal-set.sh alternates oxygen-live-0/1 so open applications see
      # a wallpaper recolour without fighting Qt's icon cache.
      kdeglobals.KDE.widgetStyle = "oxygen";
      kwalletrc.Wallet."First Use" = false;
      # The exact titlebar top uses: close / minimize / maximize at left, keep
      # above at right, Oxygen decoration, no decoration shadow. These used to
      # be deliberately mutable, which preserved top while book stayed on its
      # old `| LFIX` layout. A future layout change belongs here so both hosts
      # move together.
      kwinrc."org.kde.kdecoration2" = {
        ButtonsOnActiveWindowGlow = false;
        ButtonsOnLeft = "XIM";
        ButtonsOnRight = "F";
        ShadowSize = 0;
        theme = "Oxygen";
      };
      kwinrc.Desktops.Number = 1;
      kwinrc.Desktops.Rows = 1;
      kwinrc.Tiling.padding = 4;
      kwinrc.Xwayland.Scale = if host == "air" then 2 else 1;
      plasma-localerc.Formats.LANG = "en_US.UTF-8";
    };
  };

  # plasma-manager's generated panel and wallpaper scripts call bare `qdbus`.
  # Plasma launches this desktop entry as a transient systemd user service on
  # Fedora, whose PATH does not include the Nix profile; both scripts then fail
  # and Plasma keeps its stock panel. Replace only the generated launcher with
  # a wrapper that pins the matching Qt tool for both hosts.
  xdg.configFile."autostart/plasma-manager-autostart.desktop".text = lib.mkForce ''
    [Desktop Entry]
    Type=Application
    Name=Plasma Manager theme application
    Exec=${plasmaManagerLogin}
    X-KDE-autostart-condition=ksmserver
  '';

  # KConfig remembers a toolbar only after Konsole has opened once, and a
  # package upgrade can restore its stock visible toolbar before that state is
  # read.  The user-local entry wins over the packaged one on both hosts and
  # makes the purposeful Top layout unambiguous for every launcher/runner
  # invocation. Dynamic.colorscheme paints its own opaque Oxygen window field,
  # so terminal text never becomes transparent to the desktop behind it.
  xdg.dataFile."applications/org.kde.konsole.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Konsole
    GenericName=Terminal
    Comment=Terminal emulator
    Exec=${pkgs.kdePackages.konsole}/bin/konsole --hide-menubar --hide-toolbars
    Icon=utilities-terminal
    Categories=Qt;KDE;System;TerminalEmulator;
    Terminal=false
    StartupNotify=true
    DBusActivatable=false
  '';

  # Push the `mice` values at a RUNNING KWin, because writing kcminputrc does
  # not reach one: KWin reads a device's libinput settings when the device is
  # ADDED and never re-reads the file, so a switch used to land silently and
  # take effect only at the next login. On 2026-08-26 that cost a round trip —
  # kcminputrc read flat/-0.200 while KWin's own properties still read
  # adaptive/0, and the trackball still felt wrong. This is the same D-Bus
  # interface the System Settings KCM writes.
  #
  # A no-op when KWin is not on the bus (a Hyprland session, a headless
  # activation over ssh), and it matches on the libinput device NAME, so a
  # mouse that is not plugged in simply has no object to match.
  home.activation.kwinPointerSettings =
    lib.hm.dag.entryAfter [ "writeBoundary" "configure-plasma" ] ''
      if command -v busctl >/dev/null 2>&1 \
         && [ -n "''${DBUS_SESSION_BUS_ADDRESS:-}" ] \
         && busctl --user status org.kde.KWin >/dev/null 2>&1; then
        for obj in $(busctl --user tree org.kde.KWin 2>/dev/null \
                     | grep -o '/org/kde/KWin/InputDevice/event[0-9]*'); do
          devname=$(busctl --user get-property org.kde.KWin "$obj" \
                      org.kde.KWin.InputDevice name 2>/dev/null \
                    | sed -e 's/^s "//' -e 's/"$//')
          case "$devname" in
${lib.concatMapStrings (m: ''
            ${lib.escapeShellArg m.name})
              $DRY_RUN_CMD busctl --user set-property org.kde.KWin "$obj" \
                org.kde.KWin.InputDevice pointerAccelerationProfileFlat b ${
                  # plasma-manager's "none" IS libinput's flat profile (the
                  # option's `apply` turns it into PointerAccelerationProfile=1);
                  # here the list is raw, so match the string.
                  if m.accelerationProfile == "none" then "true" else "false"
                } || true
              $DRY_RUN_CMD busctl --user set-property org.kde.KWin "$obj" \
                org.kde.KWin.InputDevice pointerAcceleration d -- ${toString m.acceleration} || true
              ;;
'') mice}
          esac
        done
      fi
    '';
}
