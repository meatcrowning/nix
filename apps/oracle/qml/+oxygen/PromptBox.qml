import QtQuick
import "../+plasma" as Plasma

// Oxygen is selected before the generic Plasma selector. Route it explicitly
// to the native KDE control instead of allowing the selector to fall through
// to ../PromptBox.qml, whose Theme.bgAlt rectangle is the Hyprland face.
// Plasma.PromptBox owns the real qqc2-desktop-style TextArea and Button, so
// Oxygen supplies its View/Base roles, focus frame, scrollbar and relief.
// Keep the same API and `face` value as the generic Plasma twin; Root.qml and
// the existing face harness treat both as the one KDE implementation.
Plasma.PromptBox {
    face: "plasma"
}
