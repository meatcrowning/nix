import QtQuick
import Quickshell
import Quickshell.Wayland

// Vertical list of RUNNING PROGRAMS for the CLASSIC bar (this desktop is locked
// to a single workspace — these replaced the old workspace squares). One cell
// per toplevel; the cell itself (icon, focus treatment, click-to-focus /
// click-to-minimize, tooltip, right-click menu) is TaskCell.qml, shared with
// the dock panel's horizontal header (DockHeader.qml) so the behaviour exists
// in exactly one place.
//
// Clicking a cell activates its window. That's also how minimized windows come
// back: the hyprvtb titlebar plugin slides a minimized window off the right
// screen edge and slides it back in when the window is focused again — which is
// exactly what activate() causes. A ROLLED-UP window is the exception, since
// it is hidden rather than parked: clicking it un-shades it instead (TaskCell).
//
// Uses the Wayland foreign-toplevel list (works standalone on this build; it's
// only the Hyprland IPC *mapping* protocol that's missing, which we don't need
// here since appId/title/activated all ride the Wayland list).
Column {
    id: root
    spacing: Theme.gap

    Repeater {
        model: ToplevelManager.toplevels
        delegate: TaskCell {}
    }
}
