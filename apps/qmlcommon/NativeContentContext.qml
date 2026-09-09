import QtQuick
import org.kde.kirigami as Kirigami

// Select native content roles on the parent Item. A Window's child Items are
// parented to contentItem, so the same component serves both root types.
// This forwards KDE's colour set; it contains no palette or colour literals.
Item {
    id: context
    readonly property bool plasma: typeof DeskStyle !== "undefined" && DeskStyle.plasma === true
    Binding {
        target: context.parent ? context.parent.Kirigami.Theme : null
        property: "inherit"
        value: false
        when: context.plasma
    }
    Binding {
        target: context.parent ? context.parent.Kirigami.Theme : null
        property: "colorSet"
        value: Kirigami.Theme.View
        when: context.plasma
    }
}
