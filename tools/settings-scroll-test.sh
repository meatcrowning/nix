#!/usr/bin/env bash
# Regression test for the Settings window's per-page scroll memory.
#
# Nine pages behind one Loader used to share one `contentY`. Switching from a
# long page to a short one let the Flickable clamp it, and nothing ever put it
# back — so returning to the long page landed you somewhere neither page chose.
# That was "the settings scroll position keeps getting hijacked", and it is
# invisible to a static check: the position is only wrong AFTER a swap, and only
# when the two pages differ in height.
#
# Drives the REAL Settings.qml through the four hooks on its root
# (page / scrollAt / scrollMax / scrollTo) — the thing under test is its
# Loader/Flickable wiring, so a mock would test nothing. Offscreen, on a private
# DBus session, from a throwaway copy of the shell files: its window never
# reaches a screen, and his own Settings window, if one is open, is untouched.
#
# Usage: tools/settings-scroll-test.sh     (exit 0 = every check passed)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/../home/prog/quickshell-files"

export QT_QPA_PLATFORM=offscreen
# shellcheck source=lib/session-guard.sh
. "$HERE/lib/session-guard.sh"
sg_require_offscreen

WORK="$(mktemp -d "${TMPDIR:-/tmp}/settings-scroll-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

export XDG_CONFIG_HOME="$WORK/config"
mkdir -p "$XDG_CONFIG_HOME"
cp "$SRC"/*.qml "$WORK/"
[ -d "$SRC/scripts" ] && cp -r "$SRC/scripts" "$WORK/"

cat >"$WORK/TestScroll.qml" <<'QML'
import QtQuick
import Quickshell

Scope {
    id: t
    property int failures: 0
    function check(name, got, want) {
        const ok = JSON.stringify(got) === JSON.stringify(want);
        if (!ok) t.failures++;
        console.warn((ok ? "PASS " : "FAIL ") + name
                     + "  got=" + JSON.stringify(got) + " want=" + JSON.stringify(want));
    }

    Loader { id: settings; source: "Settings.qml" }

    // Where the second park actually landed. Asserting a literal here was
    // wrong: scrollTo clamps to the page's max, so the number depends on the
    // page's height, which depends on how many senders are in its app list.
    property real parked2: -1

    property int n: 0
    Timer {
        interval: 700
        repeat: true
        running: true
        onTriggered: {
            const s = settings.item;
            if (!s) { console.warn("FAIL Settings.qml did not load"); Qt.exit(1); return; }
            switch (t.n) {
            case 0:
                t.check("an unknown page key is refused", s.page("nope"), false);
                // notifs is the tallest page; panel is one of the shortest.
                t.check("opening a page by key works", s.page("notifs"), true);
                break;
            case 1:
                t.check("the tall page is scrollable", s.scrollMax() > 400, true);
                s.scrollTo(400);
                break;
            case 2:
                t.check("parked partway down it", Math.round(s.scrollAt()), 400);
                s.page("panel");
                break;
            case 3:
                // With one shared contentY this landed at the SHORT page's
                // maximum, not at its top — the visible bug.
                t.check("the short page opens at its own top",
                        Math.round(s.scrollAt()), 0);
                t.check("...and the short page really is shorter",
                        s.scrollMax() < 400, true);
                s.page("notifs");
                break;
            case 4:
                t.check("the tall page comes back to where it was left",
                        Math.round(s.scrollAt()), 400);
                s.scrollTo(700);
                t.parked2 = Math.round(s.scrollAt());
                t.check("the second park moved it somewhere new",
                        t.parked2 !== 400 && t.parked2 > 400, true);
                s.page("system");
                break;
            case 5:
                t.check("a third page also opens at its own top",
                        Math.round(s.scrollAt()), 0);
                s.page("notifs");
                break;
            case 6:
                t.check("and the tall page remembers its LATEST position",
                        Math.round(s.scrollAt()), t.parked2);
                console.warn("RESULT " + (t.failures === 0 ? "ALL PASS" : t.failures + " FAILURES"));
                Qt.callLater(() => Qt.exit(t.failures === 0 ? 0 : 1));
                break;
            }
            t.n = t.n + 1;
        }
    }
}
QML

out="$(env -u WAYLAND_DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE timeout 90 \
         dbus-run-session -- qs -p "$WORK/TestScroll.qml" 2>&1)"
rc=$?
printf '%s\n' "$out" | sed 's/\x1b\[[0-9;]*m//g' \
    | grep -E '^\s*WARN qml: (PASS|FAIL|RESULT)' | sed 's/^\s*WARN qml: //'
if [ $rc -ne 0 ]; then
    echo "settings-scroll-test: FAILED (exit $rc)"
    printf '%s\n' "$out" | sed 's/\x1b\[[0-9;]*m//g' | tail -20
    exit 1
fi
echo "settings-scroll-test: all checks passed"
