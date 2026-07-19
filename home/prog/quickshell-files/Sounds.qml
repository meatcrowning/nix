pragma Singleton
import Quickshell
import QtQuick

// Windows Vista system sounds (user-provided, extracted to
// ~/.local/share/sounds/vista — NOT in the repo, the wavs are Microsoft's).
// Central playback so every component names a file, not a pipeline. Event
// map (who calls what):
//   login          -> "Windows Logon Sound.wav"     (hyprland.lua autostart)
//   notifications  -> Balloon / Exclamation          (Notifications.qml)
//   volume change  -> "Windows Ding.wav" throttled   (Osd.qml)
//   trash change   -> "Windows Recycle.wav"          (vista-trash-sound.path)
//   sudo prompt    -> "Windows User Account Control.wav" (sudo-askpass wrapper)
// (Click and minimize/restore sounds existed briefly and were removed by
// request — keep interaction sounds to the five events above.)
Singleton {
    id: root

    function play(file) {
        // argv-splice, no interpolation — filenames contain spaces.
        Quickshell.execDetached(["sh", "-c",
            'exec pw-play "$HOME/.local/share/sounds/vista/$1" 2>/dev/null', "_", file]);
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
