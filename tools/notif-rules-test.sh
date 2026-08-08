#!/usr/bin/env bash
# Regression test for the notification gate: the per-sender rules, the DND
# conditions, the seen registry, and the notifs settings page that edits them.
#
# Notifications.qml decides, for every toast, whether it appears and whether it
# makes a sound. That decision table is the one thing here whose failure mode is
# SILENCE — a wrong branch does not throw, it just eats a notification, and the
# obvious way to test it (send one and look) is exactly what this repo forbids.
# So: a private DBus session, an offscreen Qt platform, a throwaway copy of the
# shell files with their own settings.json, and no contact with his session at
# all. The harness holds the branch order under test as a transcription of the
# shipped gate — if you reorder the real one, reorder it here too.
#
# Usage: tools/notif-rules-test.sh        (exit 0 = every check passed)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/../home/prog/quickshell-files"

# Exported before the guard reads it, and inherited by every qs below: this is
# the thing sg_require_offscreen checks, so setting it per-invocation instead
# would leave the guard looking at his session and refusing.
export QT_QPA_PLATFORM=offscreen
# shellcheck source=lib/session-guard.sh
. "$HERE/lib/session-guard.sh"
sg_require_offscreen

WORK="$(mktemp -d "${TMPDIR:-/tmp}/notif-rules-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

cp "$SRC"/*.qml "$WORK/"
[ -d "$SRC/scripts" ] && cp -r "$SRC/scripts" "$WORK/"

cat >"$WORK/TestGate.qml" <<'QML'
import QtQuick
import Quickshell

// The decision table: who gets a toast, and who gets a sound.
Scope {
    id: t
    property int failures: 0
    function check(name, got, want) {
        const ok = JSON.stringify(got) === JSON.stringify(want);
        if (!ok) t.failures++;
        console.warn((ok ? "PASS " : "FAIL ") + name
                     + "  got=" + JSON.stringify(got) + " want=" + JSON.stringify(want));
    }
    function fake(appName, desktopEntry, urgency) {
        return { appName: appName, desktopEntry: desktopEntry, urgency: urgency };
    }

    // Transcribed from Notifications.onNotification: same branches, same order.
    // The singleton's own handler cannot be called directly (it wants a real
    // Notification off the bus), but every predicate in it is a helper below.
    function wouldPopup(n) {
        const rule = Notifications.ruleFor(Notifications.keyFor(n));
        const critical = n.urgency === 2;
        if (!rule.popup) return false;
        if (n.urgency === 0 && !SettingsStore.d.notifLowPopup) return false;
        if (Notifications.dndNow()
                && !(critical ? SettingsStore.d.notifCriticalInDnd : rule.dnd)) return false;
        return true;
    }
    function wouldSound(n) {
        if (!wouldPopup(n)) return false;
        const rule = Notifications.ruleFor(Notifications.keyFor(n));
        return rule.sound && !SettingsStore.d.notifSoundMute;
    }

    Component.onCompleted: {
        const d = SettingsStore.d;

        t.check("keyFor prefers the desktop entry",
                Notifications.keyFor(t.fake("Vivaldi", "vivaldi-stable", 1)), "vivaldi-stable");
        t.check("keyFor falls back to the app name, lowercased",
                Notifications.keyFor(t.fake("KDE Connect", "", 1)), "kde connect");
        t.check("keyFor of an anonymous sender is @other",
                Notifications.keyFor(t.fake("", "", 1)), "@other");

        t.check("default: normal pops", t.wouldPopup(t.fake("a", "a", 1)), true);
        t.check("default: low pops", t.wouldPopup(t.fake("a", "a", 0)), true);
        t.check("default: normal sounds", t.wouldSound(t.fake("a", "a", 1)), true);

        d.notifLowPopup = false;
        t.check("lowPopup off: low is dropped", t.wouldPopup(t.fake("a", "a", 0)), false);
        t.check("lowPopup off: normal survives", t.wouldPopup(t.fake("a", "a", 1)), true);
        d.notifLowPopup = true;

        d.doNotDisturb = true;
        t.check("dnd: normal suppressed", t.wouldPopup(t.fake("a", "a", 1)), false);
        t.check("dnd: critical through by default", t.wouldPopup(t.fake("a", "a", 2)), true);
        d.notifCriticalInDnd = false;
        t.check("dnd + criticalInDnd off: critical suppressed too",
                t.wouldPopup(t.fake("a", "a", 2)), false);
        d.notifCriticalInDnd = true;
        d.doNotDisturb = false;
        t.check("dnd off again: normal through", t.wouldPopup(t.fake("a", "a", 1)), true);

        d.notifDndUntil = Date.now() + 60000;
        t.check("timed dnd armed: dndNow true", Notifications.dndNow(), true);
        t.check("timed dnd armed: normal suppressed", t.wouldPopup(t.fake("a", "a", 1)), false);
        d.notifDndUntil = Date.now() - 1000;
        t.check("timed dnd lapsed: dndNow false", Notifications.dndNow(), false);
        t.check("timed dnd lapsed: normal through", t.wouldPopup(t.fake("a", "a", 1)), true);
        d.notifDndUntil = 0;

        d.notifRules = { "quiet.app": { popup: false } };
        t.check("rule popup:false suppresses that sender",
                t.wouldPopup(t.fake("Quiet", "quiet.app", 1)), false);
        t.check("rule popup:false binds even for critical",
                t.wouldPopup(t.fake("Quiet", "quiet.app", 2)), false);
        t.check("another sender is unaffected", t.wouldPopup(t.fake("b", "b.app", 1)), true);

        d.notifRules = { "loud.app": { dnd: true } };
        d.doNotDisturb = true;
        t.check("rule dnd:true pierces do not disturb",
                t.wouldPopup(t.fake("Loud", "loud.app", 1)), true);
        t.check("a sender without it does not", t.wouldPopup(t.fake("b", "b.app", 1)), false);
        d.doNotDisturb = false;

        d.notifRules = { "mute.app": { sound: false } };
        t.check("rule sound:false keeps the toast", t.wouldPopup(t.fake("M", "mute.app", 1)), true);
        t.check("rule sound:false drops the chime", t.wouldSound(t.fake("M", "mute.app", 1)), false);

        d.notifRules = { "@other": { popup: false }, "yes.app": { popup: true } };
        t.check("@other popup:false suppresses an unlisted sender",
                t.wouldPopup(t.fake("x", "x.app", 1)), false);
        t.check("an explicit rule overrides @other",
                t.wouldPopup(t.fake("y", "yes.app", 1)), true);
        d.notifRules = ({});

        d.notifSoundMute = true;
        t.check("soundMute: toast stays", t.wouldPopup(t.fake("a", "a", 1)), true);
        t.check("soundMute: chime goes", t.wouldSound(t.fake("a", "a", 1)), false);
        d.notifSoundMute = false;

        d.notifSeen = ({});
        Notifications._recordSeen(t.fake("Vivaldi", "vivaldi-stable", 1));
        Notifications._recordSeen(t.fake("Vivaldi", "vivaldi-stable", 1));
        Notifications._recordSeen(t.fake("KDE Connect", "", 1));
        t.check("seen records one entry per sender, keyed and labelled",
                SettingsStore.d.notifSeen,
                { "vivaldi-stable": "Vivaldi", "kde connect": "KDE Connect" });

        console.warn("RESULT " + (t.failures === 0 ? "ALL PASS" : t.failures + " FAILURES"));
        Qt.callLater(() => Qt.exit(t.failures === 0 ? 0 : 1));
    }
}
QML

cat >"$WORK/TestPage.qml" <<'QML'
import QtQuick
import Quickshell

// The settings page that edits those rules: does it build, does the per-app
// list mirror the seen registry, does a row write back?
Scope {
    id: t
    property int failures: 0
    function check(name, got, want) {
        const ok = JSON.stringify(got) === JSON.stringify(want);
        if (!ok) t.failures++;
        console.warn((ok ? "PASS " : "FAIL ") + name
                     + "  got=" + JSON.stringify(got) + " want=" + JSON.stringify(want));
    }

    FloatingWindow {
        implicitWidth: 640
        implicitHeight: 580
        visible: true
        Loader { id: pageLoader; width: 600; source: "SetPgNotifs.qml" }
    }

    Timer {
        interval: 400
        running: true
        onTriggered: {
            const page = pageLoader.item;
            t.check("the page instantiated", page !== null, true);
            if (!page) { Qt.exit(1); return; }
            t.check("the page has height", page.implicitHeight > 200, true);
            t.check("seen senders are listed",
                    page.seenApps.map(a => a.key), ["kde connect", "vivaldi-stable"]);
            t.check("labels come from the registry",
                    page.seenApps.map(a => a.label), ["KDE Connect", "Vivaldi"]);

            let row = null;
            function walk(o) {
                if (!o || !o.children) return;
                for (const c of o.children) {
                    if (c.appKey !== undefined && c.appKey === "vivaldi-stable") row = c;
                    walk(c);
                }
            }
            walk(page);
            t.check("the vivaldi row exists", row !== null, true);
            if (!row) { Qt.exit(1); return; }

            t.check("an unruled row is not marked customised", row.customised, false);
            t.check("its effective popup is the default", row._eff("popup"), true);

            row.setField("popup", false);
            t.check("setField wrote the rule",
                    SettingsStore.d.notifRules, { "vivaldi-stable": { popup: false } });
            t.check("the row now reads customised", row.customised, true);
            t.check("its effective popup followed", row._eff("popup"), false);

            row.setField("popup", true);
            SettingsStore.d.notifRules = { "@other": { sound: false },
                                           "vivaldi-stable": { popup: true } };
            t.check("the row inherits @other's sound", row._eff("sound"), false);
            t.check("the row keeps its own popup", row._eff("popup"), true);

            row.clearRule();
            t.check("clearRule removed only that key",
                    SettingsStore.d.notifRules, { "@other": { sound: false } });

            page._setDnd("1h");
            t.check("arming stores the duration", SettingsStore.d.notifDndFor, 60);
            t.check("arming stamps an instant in the future",
                    SettingsStore.d.notifDndUntil > Date.now() + 59 * 60000, true);
            t.check("the picker shows what was armed", page._dndLabel(), "1h");
            page._setDnd("off");
            t.check("disarming clears both",
                    [SettingsStore.d.notifDndFor, SettingsStore.d.notifDndUntil], [0, 0]);

            console.warn("RESULT " + (t.failures === 0 ? "ALL PASS" : t.failures + " FAILURES"));
            Qt.callLater(() => Qt.exit(t.failures === 0 ? 0 : 1));
        }
    }
}
QML

# The page harness needs senders in the registry before it builds the list.
python3 - "$WORK/settings.json" <<'PY'
import json, sys
p = sys.argv[1]
d = {}
d["notifSeen"] = {"vivaldi-stable": "Vivaldi", "kde connect": "KDE Connect"}
d["notifRules"] = {}
json.dump(d, open(p, "w"), indent=2)
PY

run() {
    local name="$1" file="$2" out rc
    # -u on both: a Quickshell that inherited his session's signature would find
    # a real compositor, and this harness must not be able to reach one. The
    # private bus is the other half — the shell files include a notification
    # SERVER, and it must never contest the name his panel owns.
    out="$(env -u WAYLAND_DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE timeout 90 \
             dbus-run-session -- qs -p "$WORK/$file" 2>&1)"
    rc=$?
    printf '%s\n' "$out" | sed 's/\x1b\[[0-9;]*m//g' | grep -E '^\s*WARN qml: (PASS|FAIL|RESULT)' \
        | sed 's/^\s*WARN qml: //'
    if [ $rc -ne 0 ]; then
        echo "FAIL $name: exit $rc"
        printf '%s\n' "$out" | sed 's/\x1b\[[0-9;]*m//g' | tail -20
        return 1
    fi
    echo "OK   $name"
}

fails=0
echo "== the gate =="
run "gate" TestGate.qml || fails=1
echo "== the page =="
run "page" TestPage.qml || fails=1

if [ $fails -ne 0 ]; then
    echo "notif-rules-test: FAILED"
    exit 1
fi
echo "notif-rules-test: all checks passed"
