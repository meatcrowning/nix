import QtQuick
import Quickshell

// The cava spectrum, on its own so both surfaces that draw it are the same
// object: the media widget's big one (MediaContent.qml) and the small one in
// the classic bar's status row when the panel is on a top/bottom edge, where
// the vertical VU meter does not fit (StatusPanel.qml).
//
// It draws only; the FEED is the Media singleton's, and a consumer has to
// declare itself with `Media.watch(obj, on)` or cava never spawns.
// ---- spectrum: mediaSpectrumBars vertical bars ----------------------
// cava's 0-100 is roughly linear in amplitude, and real music spends almost
// all its time in the bottom third of that (measured medians 15, p90 49), so
// a straight height mapping draws stubs that twitch by a pixel and reads as
// "unresponsive". Curve it: gamma 0.55 pulls that same data up to med ~35 /
// p90 ~68 without touching the top end (100 still maps to 100), so the bars
// use the widget's full height and the same transient moves visibly further.
// Do this here rather than raising cava's sensitivity — autosens owns that,
// and fighting it is what forces per-track fiddling.
Item {
    id: spec
    readonly property int nbars: SettingsStore.d.mediaSpectrumBars
    readonly property real gamma: 0.55
    // The measuring grid: `gridRows` hairlines dividing the spectrum into
    // equal rows, top to bottom, in `Theme.border` — the hairline the volume
    // column and the tile frames already use, so the grid arrives without a
    // new colour in it. No labels and no shading, both by request: rules on
    // the plain background, nothing else. (Alternating a subtle fill was
    // tried twice, once on every other BAR and once on every other grid ROW,
    // and rejected both times. Don't re-add either.)
    //
    // EVENLY SPACED IN PIXELS, [his] — a deliberate reversal worth recording
    // so it does not get "fixed" back. It was briefly a gamma-mapped ladder
    // (100/75/50/25/12.5/6.25 of cava's scale, i.e. -0 to -24 dB, each rule
    // landing where that amplitude actually draws) on the reasoning that an
    // evenly-spaced rule measures nothing in particular once `gamma` has
    // bent the axis. True, but it bought a numeric honesty nothing labelled
    // and cost the thing a grid is FOR: rules bunched into the top half,
    // uncountable, most of them dark. Even spacing it is; the dB reading is
    // not coming back without labels to carry it.
    //
    // Eight rows because it halves cleanly — the midpoint, the quarters and
    // the eighths are all rules, so the eye can bisect its way to a level
    // without counting from the bottom — and because it is comfortably more
    // than the "3 or 4" that read as too few.
    readonly property int gridRows: 8
    // Minimum legible row height. Derived from the row COUNT rather than
    // written as a height literal, so changing `gridRows` moves the
    // threshold by itself — below it the grid is a smear rather than
    // something countable, and it also keeps these out of the degenerate
    // layout passes construction and teardown produce.
    readonly property int minGridPx: 6
    Repeater {
        model: spec.gridRows
        Rectangle {
            required property int index
            anchors { left: parent.left; right: parent.right }
            y: Math.round(spec.height * index / spec.gridRows)
            height: 1
            color: Theme.border
            visible: spec.height >= spec.gridRows * spec.minGridPx
        }
    }

    // Bars are gapless, so they can't be laid out by a Row with spacing 0: at
    // 32 buckets the per-bar width is fractional, and rounding each one
    // independently leaves subpixel seams between them. Position from the
    // shared edge instead — bar i spans round(w*i/n)..round(w*(i+1)/n), so one
    // bar's right edge IS the next one's left edge and the row stays exactly
    // `width` wide however the division falls.
    Repeater {
        model: spec.nbars
        Item {
            required property int index
            readonly property int x0: Math.round(spec.width * index / spec.nbars)
            x: x0
            width: Math.max(1, Math.round(spec.width * (index + 1) / spec.nbars) - x0)
            height: spec.height

            // level
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: Math.max(1, spec.height
                    * Math.pow(Math.max(0, Media.spectrumLevels[index] || 0) / 100, spec.gamma))
                // UNIFORM. Every other BAR was briefly shaded a rung down to
                // Theme.dim; that was a misreading of "every other" — the
                // alternation belongs to the grid ROWS above, and the bars
                // are one series drawn in one colour.
                color: Theme.textDim
                // cava already smooths (noise_reduction) and feeds 60fps, so
                // this is a second low-pass on top. Keep it just long enough
                // to absorb a dropped frame, not to re-add lag.
                Behavior on height { NumberAnimation { duration: 25 } }
            }

            // peak marker — same gamma as the bar so it lines up with the bar
            // top on a fresh hit. Deliberately NOT animated: the fall is
            // already interpolated frame-by-frame by the gravity model, and a
            // Behavior here would drag the marker behind the peak it is
            // supposed to be pinning.
            //
            // The bar/marker pair is a light-on-dark split of the same hue:
            // the bars take Theme.textDim (the elapsed/remaining time colour)
            // and the markers the brighter Theme.accent, so a marker reads
            // both against the background it usually floats over and against
            // its own bar on the frames it rides the top. 2px tall — at 1px a
            // falling marker was too faint to track.
            Rectangle {
                anchors { left: parent.left; right: parent.right }
                height: 2
                y: Math.min(spec.height - height, Math.max(0, spec.height - height - spec.height
                    * Math.pow(Math.max(0, Media.spectrumPeaks[index] || 0) / 100, spec.gamma)))
                color: Theme.accent
                visible: (Media.spectrumPeaks[index] || 0) > 0
            }
        }
    }
}
