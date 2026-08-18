import QtQuick

// The seed row, shared so every preset chooses the seed the same way.
//
// Three controls, and the honesty rule (docs/DESIGN.md §10) decides which are
// live: the number is editable unless "random" or "reuse last" is driving it;
// "random" rolls a fresh seed each batch; "reuse last" re-runs at the exact
// seed the previous batch used (App.lastSeed) and so is dead until there IS a
// previous batch. The edit preset uses this too (SeedPanel), because its graph
// honours the seed exactly like the image presets do — it just had no control.
Field {
    label: "seed"
    hint: "The starting noise. 'reuse last' re-runs the previous batch's seed; "
          + "with both off, the number is used as-is (batches walk up from it)."
    Row {
        spacing: 8
        Spin {
            width: 150
            // While "reuse last" is on, show the seed that will actually run
            // (the remembered one), not the stale typed value beneath it.
            value: (root.gen.reuseSeed && App.lastSeed >= 0) ? App.lastSeed
                                                             : root.gen.seed
            from: 0; to: 9007199254740992; step: 1
            enabled: !root.gen.randomSeed && !root.gen.reuseSeed
            opacity: enabled ? 1 : 0.45
            onEdited: function (v) { root.set("seed", v) }
        }
        Toggle {
            label: "random"
            checked: root.gen.randomSeed
            enabled: !root.gen.reuseSeed
            opacity: enabled ? 1 : 0.45
            anchors.verticalCenter: parent.verticalCenter
            onToggled: function (v) { root.set("randomSeed", v) }
        }
        Toggle {
            label: "reuse"
            checked: root.gen.reuseSeed
            enabled: App.lastSeed >= 0
            opacity: enabled ? 1 : 0.45
            anchors.verticalCenter: parent.verticalCenter
            onToggled: function (v) {
                root.set("reuseSeed", v)
                if (v) root.set("randomSeed", false)   // reuse overrides random
            }
        }
    }
}
