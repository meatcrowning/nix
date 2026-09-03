import QtQuick

// The seed row, shared so every preset chooses the seed the same way.
//
// It follows rgthree's useful distinction: random is the literal -1 in the
// box, new fixed rolls one concrete number NOW, and last restores the seed the
// last queued batch actually got. Last remains legible but is disabled until it
// can change something — a state, not a missing control (docs/DESIGN.md §10).
Field {
    id: field
    // The seed's own panel/title supplies its name. Unlike ordinary paired
    // form rows, this is a compact control group: reserve no label gutter so
    // its number box can use the whole controls column.
    label: ""
    labelWidth: 0
    hint: "-1 is random for every queued batch. new fixed rolls one concrete "
          + "seed now; last restores the previous queued seed."

    readonly property bool lastAvailable: App.lastSeed >= 0
                                        && App.lastSeed !== root.gen.seed

    function randomSeed() {
        root.set("seed", -1)
        root.set("randomSeed", true)
        root.set("reuseSeed", false)
    }

    function newFixedSeed() {
        var seed = App.freshSeed()
        if (seed < 0) return
        root.set("seed", seed)
        root.set("randomSeed", false)
        root.set("reuseSeed", false)
    }

    function useLastSeed() {
        if (!field.lastAvailable) return
        root.set("seed", App.lastSeed)
        root.set("randomSeed", false)
        root.set("reuseSeed", false)
    }

    Column {
        // Field keeps a 6px gap after any label. This component has none, so
        // reclaim that gap: both the seed box and button row span the whole
        // controls column rather than ending short of its left edge.
        x: -6
        width: parent.width + 6
        spacing: 4
        Spin {
            width: parent.width
            value: root.gen.seed
            from: -1; to: 9007199254740992; step: 1
            onEdited: function (v) {
                root.set("seed", v)
                root.set("randomSeed", v < 0)
                root.set("reuseSeed", false)
            }
        }
        Row {
            id: buttons
            width: parent.width
            spacing: 8
            TextButton {
                label: "[ random ]"
                lit: root.gen.seed < 0
                anchors.verticalCenter: parent.verticalCenter
                onClicked: field.randomSeed()
            }
            TextButton {
                label: "[ new fixed ]"
                anchors.verticalCenter: parent.verticalCenter
                onClicked: field.newFixedSeed()
            }
            TextButton {
                id: lastButton
                objectName: "seedLast"
                label: "[ last ]"
                enabled: field.lastAvailable
                anchors.verticalCenter: parent.verticalCenter
                onClicked: field.useLastSeed()
            }
        }
    }
}
