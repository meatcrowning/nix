pragma Singleton
import Quickshell
import QtQuick

// Windows Vista system sounds. The wavs are Microsoft's, so they live in a
// private submodule (github.com/meatcrowning/vista-sounds → sounds/), symlinked
// to ~/.local/share/sounds/vista by home/srvs/vista-sounds.nix.
// Central playback so every component names a file, not a pipeline. Event
// map (who calls what):
//   login          -> "Windows Logon Sound.wav"     (hyprland.lua autostart)
//   notifications  -> Balloon / Exclamation          (Notifications.qml)
//   volume change  -> "Windows Ding.wav" throttled   (Osd.qml)
//   trash change   -> "Windows Recycle.wav"          (vista-trash-sound.path)
//   sudo prompt    -> "Windows User Account Control.wav" (sudo-askpass wrapper)
//   logout         -> "Windows Logoff Sound.wav"      (PowerMenu.qml)
//   reboot/off     -> "Windows Shutdown.wav"          (PowerMenu.qml)
//   battery low    -> "Windows Battery Low.wav"       (SysInfo._battAlarm)
//   battery crit   -> "Windows Battery Critical.wav"  (SysInfo._battAlarm)
// The battery pair reaches this through a TOAST rather than a direct play:
// the notification carries `x-vista-sound` naming the file, so the card and
// the sound are one event (Notifications.qml).
// (Click and minimize/restore sounds existed briefly and were removed by
// request — keep interaction sounds to the events above. Every event here is
// a system one; none of them fires on a click.)
Singleton {
    id: root

    function play(file) {
        // Master toggle: when sounds are disabled, do nothing.
        if (!SettingsStore.d.soundsEnabled)
            return;
        // argv-splice, no interpolation — filenames contain spaces. The theme
        // directory ($2) is the configured sound set (default "vista"), so the
        // path resolves under ~/.local/share/sounds/<theme>/.
        Quickshell.execDetached(["sh", "-c",
            'exec pw-play "$HOME/.local/share/sounds/$2/$1" 2>/dev/null', "_", file, SettingsStore.d.soundTheme]);
    }

    // For rapid-fire events (volume key repeat): at most one play per window.
    property double lastThrottled: 0
    function playThrottled(file, ms) {
        const now = Date.now();
        if (now - lastThrottled < (ms || 200))
            return;
        lastThrottled = now;
        play(file);
    }
}
