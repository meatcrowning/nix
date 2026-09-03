import QtQuick

// SEED FOR EDIT MODE. The edit graph feeds the seed into its noise node exactly
// like the image path does (registry._build_edit → noise_seed), so an edit is
// as reproducible as any other generation — but the sampling panel that carries
// the seed control is hidden in this preset (Main.qml, `visible: !App.isEdit`),
// so until now there was no way to pin or reuse it here. This is the one row of
// that panel the edit preset actually reads, and nothing more.
Panel {
    id: panel
    title: "seed"
    badge: root.gen.seed < 0 ? "random" : "fixed"

    SeedField {}
}
