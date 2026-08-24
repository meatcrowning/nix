{ config, pkgs, lib, host, ... }:

{
  programs.plasma = {
    enable = true;

    # book only: the "new Oxygen" KDE global theme (org.kde.oxygen — the
    # revived Oxygen look-and-feel bundled by kdePackages.oxygen, distinct
    # from the classic pre-Plasma-5 Oxygen). `plasma-apply-lookandfeel` pulls
    # in Oxygen's own colour scheme (OxygenDark), icons, cursor (Oxygen_Black)
    # and kwin decoration together, matching what its packaged defaults file
    # sets (oxygen-6.7.4/share/plasma/look-and-feel/org.kde.oxygen/contents/defaults).
    # soundTheme is separate — lookAndFeel doesn't touch Sounds.Theme. Applies
    # on next PLASMA login (programs.plasma.startup, overrideConfig=false
    # means it's a one-shot autostart script, not a live rewrite) — book's
    # live session right now is Hyprland, which this doesn't touch. Per
    # docs/DESIGN.md §"In a PLASMA session none of this applies": the apps'
    # colours already follow whatever KDE global theme is picked, so this is
    # just picking Oxygen as that theme rather than adding a new mechanism.
    # Not on top: top's Plasma session defaults to stock Breeze (or, when
    # `my.aerotheme.enable` is set, the separate aerothemeplasma session) and
    # nobody asked for Oxygen there.
    workspace = lib.mkIf (host == "air") {
      lookAndFeel = "org.kde.oxygen";
      soundTheme = "oxygen";
    };

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
      # An unfocused window dims WHOLE — docs/DESIGN.md §3.1.1, the same rule
      # the Hyprland session gets from `decoration:dim_inactive`. KWin's Dim
      # Inactive effect is a compositor scrim over deco AND client, so the two
      # halves of a window cannot disagree about focus; the colour scheme's own
      # inactive effect, which they read from different places, is held OFF by
      # home/srvs/kde-inactive-effect.nix (why, and what it measured, is there).
      # Strength is Hyprland's dim_strength 0.5, in KWin's 0-100.
      kwinrc.Plugins.diminactiveEnabled = true;
      kwinrc."Effect-diminactive".Strength = 50;
      kdeglobals."ColorEffects:Inactive".Enable = false;
      kdeglobals."KFileDialog Settings"."Automatically select filename extension" = true;
      kdeglobals."KFileDialog Settings"."Breadcrumb Navigation" = true;
      kdeglobals."KFileDialog Settings"."Show Inline Previews" = true;
      kdeglobals."KFileDialog Settings"."Sort by" = "Name";
      kdeglobals."KFileDialog Settings"."Sort directories first" = true;
      kwalletrc.Wallet."First Use" = false;
      # Titlebar buttons, right-hand group: roll up, keep above, minimize,
      # close. 'L' is the roll-up ("shade") button — the patched kwin puts that
      # character back in both button tables and implements the roll itself
      # (kwin-rollup-overlay in flake.nix). Reorder HERE, not in System
      # Settings: this value is declared, so a switch would undo a drag.
      kwinrc."org.kde.kdecoration2".ButtonsOnRight = "LFIX";
      kwinrc.Desktops.Number = 1;
      kwinrc.Desktops.Rows = 1;
      kwinrc.Tiling.padding = 4;
      kwinrc.Xwayland.Scale = if host == "air" then 2 else 1;
      plasma-localerc.Formats.LANG = "en_US.UTF-8";
    };
  };
}
