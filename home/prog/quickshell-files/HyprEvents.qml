import QtQuick
import Quickshell.Hyprland

// The compositor's own event stream, wired to the one poll that needs to keep
// up with it. WinState reads `hyprctl clients` once a second, which is fine for
// the taskbar's roll/minimize dots and far too slow for anything drawn AGAINST
// a window: unmaximizing left the notch's seam patch standing until the next
// tick, so [his] "the border of the bar only returns after the window has
// completed its 'unmaximize' animation".
//
// It does not have to wait, and neither does this: `hyprctl clients` reports a
// window's GOAL geometry, not its animated one (measured — a moved window reads
// at its destination in the same millisecond the dispatch returns), so a refresh
// at the moment of the event already sees the restored rectangle. The border
// comes back as the animation STARTS.
//
// Loaded through a Loader (shell.qml) rather than imported by WinState, so a
// Quickshell built without the Hyprland module degrades to the 1s poll instead
// of taking the whole panel down with a failed import.
Item {
    Connections {
        target: Hyprland

        function onRawEvent(event) {
            switch (event.name) {
            // Anything that moves, resizes, maps or unmaps a window changes
            // what a panel surface may be flush against.
            case "fullscreen":
            case "changefloatingmode":
            case "openwindow":
            case "closewindow":
            case "movewindow":
            case "movewindowv2":
            case "resizewindow":
            case "resizewindowv2":
            case "monitoradded":
            case "monitorremoved":
            case "workspace":
            case "focusedmon":
                WinState.refresh();
                break;
            default:
                break;
            }
        }
    }
}
