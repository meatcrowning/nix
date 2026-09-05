import QtQuick

// The seed row, shared so every preset chooses the seed the same way.
//
// It follows rgthree's useful distinction: random is the literal -1 in the
// box, new fixed rolls one concrete number NOW, and last restores the seed the
// last queued batch actually got. Last remains legible but is disabled until it
// can change something — a state, not a missing control (docs/DESIGN.md §10).
Field {
    id: field
    label: "Seed"
    hint: "-1 is random for every queued batch. new fixed rolls one concrete "
          + "seed now; last restores the previous queued seed."

    readonly property bool lastAvailable: App.lastSeed >= 0
                                        && App.lastSeed !== root.gen.seed

    function randomSeed() {
        root.set("seed", -1)
        root.set("randomSeed", true)
        root.set("reuseSeed", false)
        seedInput.showValue(-1)
    }

    function newFixedSeed() {
        var seed = App.freshSeed()
        if (seed < 0) return
        root.set("seed", seed)
        root.set("randomSeed", false)
        root.set("reuseSeed", false)
        seedInput.showValue(seed)
    }

    function useLastSeed() {
        if (!field.lastAvailable) return
        root.set("seed", App.lastSeed)
        root.set("randomSeed", false)
        root.set("reuseSeed", false)
        seedInput.showValue(App.lastSeed)
    }

    Column {
        // `parent` is Field's right-hand holder: this is the same control
        // column every other sampling row uses, after the 96px label gutter.
        width: parent.width
        spacing: 4
        SeedInput {
            id: seedInput
            // A seed is a 53-bit integer. Qt's native SpinBox is 32-bit, so
            // Plasma uses SeedInput's styled text editor instead; both faces
            // still share this exact width and editing API.
            width: buttons.width
            value: root.gen.seed
            onEdited: function (v) {
                root.set("seed", v)
                root.set("randomSeed", v < 0)
                root.set("reuseSeed", false)
            }
        }
        Row {
            id: buttons
            width: parent.width
            spacing: 4
            TextButton {
                width: Math.floor((buttons.width - buttons.spacing * 2) / 3)
                label: "[ 🎲 ]"
                lit: root.gen.seed < 0
                anchors.verticalCenter: parent.verticalCenter
                onClicked: field.randomSeed()
            }
            TextButton {
                width: Math.floor((buttons.width - buttons.spacing * 2) / 3)
                label: "[ Random Fixed ]"
                anchors.verticalCenter: parent.verticalCenter
                onClicked: field.newFixedSeed()
            }
            TextButton {
                id: lastButton
                objectName: "seedLast"
                width: buttons.width - x
                label: "[ Reuse last ]"
                enabled: field.lastAvailable
                anchors.verticalCenter: parent.verticalCenter
                onClicked: field.useLastSeed()
            }
        }
    }
}
