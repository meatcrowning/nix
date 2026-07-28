#!/usr/bin/env bash
# Regression probe for the media widget's lyrics column, offscreen and hermetic.
#
# Drives the REAL Media.qml and MediaContent.qml with real socket-shaped queue
# lines and asserts what comes out. Nothing reaches a screen and no sandbox
# monitor is needed: `qs` runs on a throwaway copy of the panel config under
# QT_QPA_PLATFORM=offscreen.
#
# Three isolations, none of them optional:
#   HOME          SettingsStore would otherwise write the user's live
#                 ~/.config/quickshell/settings.json.
#   DBUS session  a private bus (dbus-run-session) carries a FAKE MPRIS player
#                 at a fixed position, so the lit line can be measured. On the
#                 user's bus this would both see his player and publish one of
#                 ours into his panel.
#   XDG_RUNTIME_DIR   keeps every socket out of the live tree.
#
# The case that matters most is OLD-no-field: a player predating the LYRICS
# subscription sends a queue line with no `lyrics` key at all, and the drawer
# must then be exactly what it was before the feature existed. That is the
# common case, and it is the one that regressed.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/home/prog/quickshell-files"
P="$(mktemp -d)"
trap 'rm -rf "$P"' EXIT
mkdir -p "$P/home/.config/quickshell" "$P/run"
cp -r "$SRC"/. "$P/home/.config/quickshell/"

# The drawer must be OPEN or there is no queue and no lyrics column to measure.
printf '{"mediaQueueOpen":true}\n' > "$P/home/.config/quickshell/settings.json"

# Only SysInfo is stubbed: it is the one singleton MediaContent touches that
# would poll hardware. Everything else under test is the real file.
cat > "$P/home/.config/quickshell/SysInfo.qml" <<'EOF'
pragma Singleton
import QtQuick
import Quickshell
Singleton {
    property real volume: 42
    property bool muted: false
    function setVolume(v) {}
    function adjustVolume(v) {}
}
EOF

# A fake MPRIS player, so `Media.player.position` is real and the lit line can
# be asserted. Uses the player app's own interpreter (mpris_server lives there).
PYENV="$(sed -n 's|.*\(/nix/store/[^ "]*python3-[^ "/]*-env/bin/python3\).*|\1|p' \
          "$(readlink -f "$(command -v player 2>/dev/null)" 2>/dev/null)" 2>/dev/null | head -1)"
[ -x "${PYENV:-}" ] || PYENV=python3
cat > "$P/fakempris.py" <<'EOF'
import sys
from mpris_server.adapters import MprisAdapter
from mpris_server.server import Server
from mpris_server.base import PlayState
POS = float(sys.argv[1])
class Fake(MprisAdapter):
    def get_current_position(self): return int(POS * 1_000_000)
    def get_current_track(self): return None
    def metadata(self):
        return {"mpris:trackid": "/track/1", "mpris:length": 200_000_000,
                "xesam:title": "probe", "xesam:artist": ["probe"]}
    def get_playstate(self): return PlayState.PLAYING
    def is_repeating(self): return False
    def is_playlist(self): return False
    def get_shuffle(self): return False
    def can_go_next(self): return True
    def can_go_previous(self): return True
    def can_play(self): return True
    def can_pause(self): return True
    def can_seek(self): return True
    def can_control(self): return True
    def get_rate(self): return 1.0
    def get_volume(self): return 1.0
    def get_stream_title(self): return "probe"
    def get_desktop_entry(self): return ""
    def get_uri_schemes(self): return ["file"]
    def get_mime_types(self): return ["audio/mpeg"]
    def get_art_url(self, track=None): return ""
    def set_rate(self, v): pass
    def set_volume(self, v): pass
    def set_shuffle(self, v): pass
    def set_repeating(self, v): pass
    def set_loop_status(self, v): pass
    def quit(self): pass
    def next(self): pass
    def previous(self): pass
    def pause(self): pass
    def resume(self): pass
    def stop(self): pass
    def play(self): pass
    def seek(self, t, track_id=None): pass
    def open_uri(self, uri): pass
    def is_mute(self): return False
    def set_mute(self, v): pass
    def get_previous_track(self): return None
    def get_next_track(self): return None
    def metadata_from_track(self, track): return self.metadata()
s = Server(name="probeplayer", adapter=Fake())
s.publish()
print("fake mpris up", flush=True)
s.loop()
EOF

cat > "$P/home/.config/quickshell/shell.qml" <<'EOF'
import QtQuick
import Quickshell
ShellRoot {
    FloatingWindow {
        id: win
        implicitWidth: 350
        // EXACTLY the widget's own open implicitHeight. A taller window is not
        // merely wasteful: `restSlack` is sampled once at completion, before
        // SettingsStore has reported the drawer open, so a window 180px taller
        // than the widget's natural rest banks all 180 as slack and the drawer
        // computes a height of ZERO for the rest of the run — no queue rows are
        // ever realized and every row measurement comes back -1. Same trap the
        // widget's own `noteRestSlack()` comment describes, seen from outside.
        implicitHeight: 230
        color: "black"
        MediaContent { id: mc; anchors.fill: parent; active: true }

        readonly property string rows: '"tracks":[{"title":"Track One Has A Long Name","artist":"Somebody","dur":210},{"title":"Track Two","artist":"Another","dur":185}]'
        // t = 0 / 5 / 9; the fake player sits at 6.0, so line 1 is the lit one.
        readonly property string lines: '[{"t":0,"line":"first line of the song"},{"t":5,"line":"second line, quite a lot longer"},{"t":9,"line":"third"}]'

        function findLists(it, out) {
            for (let i = 0; i < it.children.length; i++) {
                const c = it.children[i];
                if (c && typeof c.itemAtIndex === "function") out.push(c);
                findLists(c, out);
            }
            return out;
        }
        function listOf(want) {          // the two lists differ by row count
            const all = findLists(mc, []);
            for (let i = 0; i < all.length; i++)
                if (all[i].count === want) { all[i].forceLayout(); return all[i]; }
            return null;
        }
        function report(tag) {
            const lv = listOf(2);
            const it = lv ? lv.itemAtIndex(0) : null;
            let dur = -1, aVis = "?", aW = -1;
            if (it) for (let i = 0; i < it.children.length; i++) {
                const c = it.children[i];
                if (c.text === "3:30") dur = Math.round(c.x);
                if (c.text === "Somebody") { aVis = "" + c.visible; aW = Math.round(c.width); }
            }
            console.warn("PROBE " + tag
                + " hasLyrics=" + Media.hasLyrics + "/" + (typeof Media.hasLyrics)
                + " synced=" + Media.lyricsSynced + "/" + (typeof Media.lyricsSynced)
                + " show=" + mc.showLyrics + " lyricsW=" + mc.lyricsW
                + " implicitHeight=" + mc.implicitHeight
                + " naturalRest=" + mc.naturalRest
                + " queueH=" + Math.round(mc.queueH) + " restSlack=" + Math.round(mc.restSlack)
                + " drawerOut=" + mc.drawerOut + " qcount=" + (lv ? lv.count : -1)
                + " durX=" + dur + " artistVis=" + aVis + " artistW=" + aW);
        }
        // One case per tick, not one per loop iteration: a ListView creates its
        // delegates on the next polish, so a same-tick read finds no rows at
        // all (measured — `durX=-1` for every case).
        property var cases: []
        property int step: -1
        Timer {
            id: stepper
            interval: 150; repeat: true
            onTriggered: {
                if (win.step >= 0) win.report(win.cases[win.step][0]);
                win.step++;
                if (win.step >= win.cases.length) { stepper.stop(); win.finish(); return; }
                Media.queueJson = win.cases[win.step][1];
            }
        }
        Timer {
            running: true; interval: 900     // let MPRIS resolve over the bus
            onTriggered: {
                // `restSlack` is sampled ONCE, at MediaContent's completion,
                // and skipped only if `Media.queueOpen` is already true then.
                // In the live panel it is: SettingsStore has long since been
                // instantiated by the bar. Here MediaContent is the singleton's
                // FIRST consumer, so it completes at the end of the load pass
                // (the documented trap) and the sample banks the whole open
                // drawer as slack, leaving queueH = 0 and no rows to measure.
                // Clearing it is the harness standing in for a panel that was
                // already running — not a correction to the widget.
                mc.restSlack = 0;
                const synced = '{"index":1,' + win.rows + ',"lyrics":{"source":"lrclib","synced":true,"lines":' + win.lines + ',"text":"x"}}';
                const cases = [
                    ["EMPTY",        ''],
                    ["OLD-no-field", '{"index":1,' + win.rows + '}'],
                    ["null",         '{"index":1,' + win.rows + ',"lyrics":null}'],
                    ["none-verdict", '{"index":1,' + win.rows + ',"lyrics":{"source":"none","synced":false,"lines":[],"text":""}}'],
                    ["SYNCED",       synced],
                    ["PLAIN",        '{"index":1,' + win.rows + ',"lyrics":{"source":"embedded","synced":false,"lines":[],"text":"plain unsynced words"}}'],
                    ["back-to-OLD",  '{"index":1,' + win.rows + '}'],
                ];
                win.cases = cases;
                win.syncedLine = synced;
                stepper.start();
            }
        }
        property string syncedLine: ""
        function finish() {
                const synced = win.syncedLine;
                // The search itself, exhaustively around every boundary.
                Media.queueJson = synced;
                console.warn("PROBE FOLLOW"
                    + " t=-1:" + Media._lineAt(-1) + " t=0:" + Media._lineAt(0)
                    + " t=4.9:" + Media._lineAt(4.9) + " t=5:" + Media._lineAt(5)
                    + " t=99:" + Media._lineAt(99));
                // …and the whole path: socket payload -> MPRIS position -> the
                // lit row's colour.
                // Colour verdict computed HERE rather than by shell regex: a
                // ListView only realizes the rows it can show, so which indices
                // exist is a property of the scroll position, and the assertion
                // that matters is "exactly the lyricIndex row is Theme.text".
                const lv = win.listOf(3);
                let n = 0, ok = true, s = "";
                if (!lv) ok = false;
                else for (let i = 0; i < lv.count; i++) {
                    const it = lv.itemAtIndex(i);
                    if (!it) continue;
                    n++;
                    const want = (i === Media.lyricIndex) ? Theme.text : Theme.textDim;
                    const got = it.children[0].color;
                    if (got != want) ok = false;
                    s += " row" + i + "=" + got;
                }
                console.warn("PROBE LIT player=" + Media.hasPlayer
                    + " pos=" + (Media.hasPlayer ? Media.player.position.toFixed(1) : "-")
                    + " lyricIndex=" + Media.lyricIndex
                    + " colours=" + (ok && n > 0 ? "ok" : "BAD") + " realized=" + n
                    + " text=" + Theme.text + " dim=" + Theme.textDim + s);
                Qt.exit(0);
        }
    }
}
EOF

OUT="$P/out.txt"
cat > "$P/run.sh" <<RUNEOF
set -u
"$PYENV" -u "$P/fakempris.py" 6.0 > "$P/mpris.log" 2>&1 &
MP=\$!
sleep 3
HOME="$P/home" XDG_CONFIG_HOME="$P/home/.config" XDG_RUNTIME_DIR="$P/run" \
  QT_QPA_PLATFORM=offscreen timeout 90 \
  qs -p "$P/home/.config/quickshell/shell.qml" --no-duplicate
kill \$MP 2>/dev/null
RUNEOF
dbus-run-session -- bash "$P/run.sh" > "$OUT" 2>&1
sed -i 's/\x1b\[[0-9;]*m//g' "$OUT"
grep -E "PROBE|Unable to assign|TypeError|ReferenceError" "$OUT" | sed 's/^ *WARN *qml: //'

fail=0
check()   { if grep -q -- "$2" "$OUT"; then echo "PASS $1"; else echo "FAIL $1  (want: $2)"; fail=1; fi; }
nocheck() { if grep -q -- "$2" "$OUT"; then echo "FAIL $1  (saw: $2)";  fail=1; else echo "PASS $1"; fi; }

echo
# The fallback. Every no-lyrics shape — including an OLD player's line, which
# has no `lyrics` key at all — collapses the column and leaves the artist and
# the duration exactly where they were before this feature existed.
for c in OLD-no-field null none-verdict back-to-OLD; do
    check "$c collapses"       "PROBE $c hasLyrics=false/boolean synced=false/boolean show=false lyricsW=0"
    check "$c keeps artist"    "PROBE $c .* artistVis=true"
    check "$c duration at 299" "PROBE $c .* durX=299 "
done
check "EMPTY collapses"        "PROBE EMPTY hasLyrics=false/boolean"
# The feature.
check "SYNCED opens the box"   "PROBE SYNCED hasLyrics=true/boolean synced=true/boolean show=true lyricsW=139"
check "SYNCED hides artist"    "PROBE SYNCED .* artistVis=false artistW=0"
check "SYNCED shifts duration" "PROBE SYNCED .* durX=147 "
check "PLAIN opens the box"    "PROBE PLAIN hasLyrics=true/boolean synced=false/boolean show=true"
check "search is exact"        "PROBE FOLLOW t=-1:-1 t=0:0 t=4.9:0 t=5:1 t=99:2"
# End to end: payload -> MPRIS position (6.0s, lines at 0/5/9) -> lit row 1.
check "MPRIS resolved"         "PROBE LIT player=true"
check "lit line follows pos"   "PROBE LIT .* lyricIndex=1 "
check "only the lit row is lit" "PROBE LIT .* colours=ok realized=[1-9]"
# Height is the whole reason the weather tile below does not move.
check "height invariant on"    "PROBE SYNCED .* implicitHeight=230 naturalRest=140"
check "height invariant off"   "PROBE OLD-no-field .* implicitHeight=230 naturalRest=140"
# No binding may take undefined, and no payload transition may throw.
nocheck "no undefined bools"   "Unable to assign \[undefined\]"
nocheck "no TypeError"         "TypeError"
nocheck "no ReferenceError"    "ReferenceError"

echo
if [ $fail -eq 0 ]; then echo "media-lyrics-probe OK"; else
    echo "media-lyrics-probe FAILED  (full log: keep \$P by editing the trap)"; fi
exit $fail
