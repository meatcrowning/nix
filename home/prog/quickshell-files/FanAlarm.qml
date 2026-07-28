import QtQuick

// "A fan that ran at a fixed speed has stopped turning" — the one fan fault on
// this desktop that can cook a CPU, and the one the fan card cannot show,
// because a fixed-speed fan is exactly what the card HIDES (Fans.fixed).
//
// PURE STATE MACHINE. No Theme, no Quickshell, no drawing, no timers: it is
// driven one call per poll by SysInfo and answers one question — "should a
// notification fire right now". That is what lets tools/fan-harness.sh replay a
// whole failure episode offscreen, which is the only way to test this at all: a
// real pump stop cannot be staged, and must certainly not be staged on the
// machine the user is sitting at.
//
// It lives in SysInfo rather than in the widget ON PURPOSE. A pump failure must
// notify whether or not the task manager happens to be open, so the detection
// cannot hang off a view that is usually not instantiated.
QtObject {
    id: root

    // Consecutive polls at a standstill before this fires. 15 x the 2s poll =
    // 30 SECONDS, and the length is a deliberate trade, not a round number:
    //
    //   * A FALSE alarm is worse than a late one. "your pump has failed, your
    //     CPU is cooking" at 3am, wrongly, once, and the notification is never
    //     trusted again — which costs more than the 30s. Every transient cause
    //     of a zero reading (a tachometer glitch, a driver hiccup, a poll
    //     landing mid-spin-up) is one or two samples; none survive fifteen.
    //   * 30s is cheap on the other side. A CPU that loses its pump throttles
    //     long before it is damaged, so the alarm does not have to win a race
    //     with thermal shutdown — it has to be believed when it arrives.
    property int alarmPolls: 15

    // A fan must have RUN for this long before its stopping means anything —
    // the same window Fans uses to decide a fan is fixed. See update().
    property int settleSamples: 30

    // name -> consecutive polls seen stopped. Reset the moment it turns again.
    property var stoppedFor: ({})
    // name -> true once fired, so one failure is one notification and not one
    // every two seconds. Cleared when the fan comes back, so a genuine SECOND
    // failure still notifies.
    property var alerted: ({})

    // The fan currently considered failed, or "" — what the card colours on.
    readonly property string active: {
        for (const n in stoppedFor)
            if (stoppedFor[n] >= alarmPolls) return n;
        return "";
    }

    // Drive one poll. Returns the name to notify about NOW, or "" for nothing.
    //
    // THREE GUARDS, and all three are paid for by something that actually
    // happened on this board:
    //
    //   * `!varied[name]` — only a fan that has NEVER changed duty. A fan the
    //     machine controls is one you can already see stop, because it has a
    //     line on the card; this alarm exists for the one that is hidden.
    //   * `hist.length >= settleSamples` — it must have RUN for a minute first.
    //     `fan5` on this board spins for ~20s and then reads 0 for ever; an
    //     unpopulated header that twitches once is not a fan that failed. This
    //     is the guard that stops the empty-header case dead.
    //   * `hadRpm[name]` — it must have had a TACHOMETER. The GPU fan reports a
    //     percentage and no RPM at all, so "0 rpm" is its normal reading; without
    //     this, an nvidia-smi hiccup would announce that the graphics card fan
    //     had failed. Costs nothing and removes a whole class of false alarm.
    function update(rows, hist, varied, hadRpm) {
        const sf = {};
        const al = {};
        for (const n in stoppedFor) sf[n] = stoppedFor[n];
        for (const n in alerted) al[n] = alerted[n];

        let fire = "";
        for (const r of (rows || [])) {
            const n = r.name;
            if (!r.stopped) {
                // Turning again: forget the episode entirely, so a second
                // failure later is a second notification.
                sf[n] = 0;
                al[n] = false;
                continue;
            }
            const h = (hist || {})[n] || [];
            const eligible = !((varied || {})[n])
                          && h.length >= settleSamples
                          && !!((hadRpm || {})[n]);
            if (!eligible) { sf[n] = 0; continue; }
            sf[n] = (sf[n] || 0) + 1;
            if (sf[n] >= alarmPolls && !al[n] && fire === "") {
                al[n] = true;
                fire = n;
            }
        }
        // A name that stopped being reported at all (the fan was removed, or the
        // whole chip went away) is dropped rather than left counting for ever.
        for (const n in sf) {
            let seen = false;
            for (const r of (rows || [])) if (r.name === n) { seen = true; break; }
            if (!seen) { delete sf[n]; delete al[n]; }
        }
        stoppedFor = sf;
        alerted = al;
        return fire;
    }
}
