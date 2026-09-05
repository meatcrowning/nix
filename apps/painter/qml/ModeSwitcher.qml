import QtQuick

// THE FOUR THINGS HE ACTUALLY MAKES, above the list of everything he could.
// [his] "there should be a switcher for anime ... real ... edition ... video"
// — one button each, and the one that is on greys the model list out, because
// while a mode is chosen the list is not what decides (ModelPicker).
//
// A mode is a SHORTCUT to a model, not a fifth kind of model: the table of
// which file each one means lives in `registry.MODES`, painter answers it
// through `App.modes()`, and this row only draws the answer. `edit` is the one
// that also changes the pipeline — it builds the Flux 2 Klein edit graph and
// the left column drops to an image well and a prompt (Main.qml).
//
// A mode whose model is not on this machine stays in the row, DISABLED, with
// one dim line saying so underneath: four buttons that are always the same
// four beat a row that silently loses one (docs/DESIGN.md §10). No tooltip on
// the buttons themselves — a ToolTipArea over a TextButton takes the hover
// that draws its own tint, and the tint is the affordance (LoraPicker's
// comment records the same ordering rule from the other side).
Column {
    id: sw
    spacing: 4

    // Rebuilt when the model list is: availability is a fact about what is on
    // disk, and a scan that lands late (book's sshfs mount) must reach this.
    property var items: []
    readonly property bool anyMissing: {
        for (var i = 0; i < items.length; i++)
            if (!items[i].available) return true
        return false
    }
    // PINNABLE, like a Field row: the preset is the one thing in the model panel
    // worth keeping in sight with the panel folded ([his] "i should be able to
    // pin the preset button row"). Same protocol — a label to know it by and a
    // value to show — and the row that gets pinned is this whole switcher, so
    // the buttons stay clickable up there.
    // THE PANEL THIS ROW IS IN, found by walking up rather than by the id
    // `panel` alone: `ParamsPanel.qml` had no such id and every row in the
    // sampling section was quietly unpinnable for it. The id is still the fast
    // path; this is the one that cannot be forgotten.
    function pinHost() {
        if (typeof panel !== "undefined" && panel && panel.pinMenu) return panel
        var p = sw.parent
        for (var i = 0; i < 8 && p; i++) {
            if (p.pinMenu !== undefined) return p
            p = p.parent
        }
        return null
    }

    property string pinLabel: "preset"
    // THIS ROW HIDES ITSELF; the panel must not park it. A parked row is
    // reparented, and a Repeater whose ancestor is reparented loses its
    // delegates — the four buttons stayed measured and laid out with nothing
    // drawn, in both faces. Nothing else here owns this `visible`, so binding
    // it to the panel's state is available where it is not for a Field (whose
    // caller often binds its own).
    property bool selfHides: true
    visible: {
        var h = sw.pinHost()
        return !h || !h.collapsed || h.pins.indexOf(sw.pinLabel) >= 0
    }
    readonly property string pinValue: App.mode === "" ? "none" : App.mode

    // Right-click anywhere in the row for its pin menu, the same as a labelled
    // row's label. A HANDLER, not a MouseArea: a positioner (this Column, the
    // Flow below) refuses to lay out an anchored child and stops laying out
    // anything at all — "Flow will not function", 44 times a load.
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: {
            var host = sw.pinHost()
            if (host) host.pinMenu(sw, point.scenePosition.x, point.scenePosition.y)
        }
    }

    function refresh() { sw.items = App.modes() }
    Component.onCompleted: refresh()
    Connections {
        target: App
        function onModelChanged() { sw.refresh() }
    }

    // A FLOW, NOT A ROW. Four buttons drawn by the KDE style are wider than a
    // 300px column, so a Row simply ran `video` off the edge and out of the
    // panel — the column is a fixed width and the button set is fixed too, so
    // the only thing left to give is a second line.
    Flow {
        id: flow
        width: sw.width
        spacing: 4

        Repeater {
            model: sw.items

            TextButton {
                required property var modelData
                label: "[ " + modelData.label + " ]"
                tone: Theme.textDim
                lit: App.mode === modelData.id
                enabled: modelData.available
                winActive: root.winActive
                // Clicking the lit one turns it OFF and hands the list back —
                // the same press that chose it, undoing it.
                onClicked: App.setMode(App.mode === modelData.id ? "" : modelData.id)
            }
        }
    }

    PixelText {
        visible: sw.anyMissing
        width: sw.width
        wrapMode: Text.Wrap
        text: "A Greyed Mode Has No Model on This Machine"
        color: Theme.dim
    }
}
