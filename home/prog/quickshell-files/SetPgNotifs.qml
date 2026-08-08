import QtQuick
import Quickshell
import Quickshell.Io

// Notifications & Sounds — the toast server behaviour, when it stays quiet, the
// per-sender rules, and the per-event sound map (urgency maps directly to a
// sound file, so they belong together).
//
// Structured after Plasma's kcm_notifications, which splits the question into
// global conditions and a per-application block; the divergences (no history,
// no badges, no per-event table, and criticals default to piercing DND) are
// noted where they sit, and in Notifications.qml at the enforcement point.
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    // ---- who is in the list ------------------------------------------------
    //
    // A list you can only edit AFTER an app has interrupted you is a list that
    // is useless exactly when you want it. Plasma builds its candidates from
    // three sources; both of the ones we lack here were measured rather than
    // assumed, so what replaces them is aimed at this desktop:
    //
    //   - `.desktop` files declaring `X-GNOME-UsesNotifications` — Plasma's
    //     primary source, and on `top` it yields ZERO: nothing in the 299
    //     entries across the system and user application dirs sets that key
    //     (it is a GNOME convention nixpkgs does not carry). Replaced by
    //     "search every installed program and pick one", below, which needs no
    //     declaration and cannot go stale.
    //   - `.notifyrc` services — 31 installed, and all of them Plasma/KDE
    //     internals (kwin, powerdevil, akonadi, plasma_workspace) that this
    //     Hyprland session never runs. Listing them would be 31 rows of noise,
    //     so they are deliberately not a source here.
    //
    // What IS: this desktop's own programs (known statically — each passes its
    // own `-a` name to notify-send), every app Plasma itself has recorded as a
    // notifier in ~/.config/plasmanotifyrc (his real history, and the only
    // place on this machine that knows firefox and discord notify), and the
    // senders the panel has learned since. Plus anything he adds by hand.

    // This desktop's own senders — the `-a` name each passes to notify-send,
    // which for these is also the only name they send (no desktop entry).
    // Keep in step with the notify-send call sites under apps/ and home/srvs/.
    readonly property var ownApps: [
        { key: "filer",      label: "filer" },
        { key: "goetia",     label: "goetia" },
        { key: "nix",        label: "repo updates" },
        { key: "painter",    label: "painter" },
        { key: "player",     label: "player" },
        { key: "quickshell", label: "the panel" },
        { key: "recording",  label: "screen recording" },
        { key: "screenshot", label: "screenshot" },
        { key: "surfer",     label: "surfer" }
    ]

    // [Applications][<desktop entry>] out of Plasma's own notification config.
    // Best-effort and read once: an absent or unreadable file is simply no
    // extra candidates, never an error — this is a bonus source, not a
    // dependency, and Plasma is an alternative session here, not a requirement.
    property var plasmaApps: []
    Process {
        running: true
        command: ["sh", "-c",
            "sed -n 's/^\\[Applications\\]\\[\\(.*\\)\\]$/\\1/p' "
            + "\"${XDG_CONFIG_HOME:-$HOME/.config}/plasmanotifyrc\" 2>/dev/null"]
        stdout: StdioCollector {
            onStreamFinished: {
                const out = [];
                for (const line of this.text.split("\n")) {
                    const k = line.trim().toLowerCase();
                    if (k)
                        out.push(k);
                }
                page.plasmaApps = out;
            }
        }
    }

    // Every installed program, for the picker. DesktopEntries scans lazily, so
    // touching `.values` is what makes it scan (same note as NotchModel).
    readonly property var installed: DesktopEntries.applications.values

    // A pretty name for a key, if any installed entry claims it.
    function _installedName(key) {
        for (const e of page.installed)
            if (e && !e.noDisplay && (e.id || "").toLowerCase() === key)
                return e.name || key;
        return "";
    }

    // The list, merged and de-duplicated. Derived through a JSON string rather
    // than straight off `notifSeen`: the store re-reads settings.json a few
    // times a second, and rebuilding this array on every one of those reloads
    // would collapse an expanded row under the pointer. The string only
    // changes when the contents do.
    readonly property string seenJson: JSON.stringify(page.d.notifSeen || {})
    property var seenApps: []
    function _rebuildSeen() {
        const byKey = {};
        // Weakest label first, strongest last: a learned sender's own app name
        // beats a guess, and this desktop's own naming beats both.
        for (const k of page.plasmaApps)
            if (k !== "@other")
                byKey[k] = page._installedName(k) || k;
        const seen = page.d.notifSeen || {};
        for (const k in seen)
            if (k !== "@other")
                byKey[k] = seen[k] || byKey[k] || k;
        for (const a of page.ownApps)
            byKey[a.key] = a.label;

        const out = [];
        for (const k in byKey)
            out.push({ key: k, label: byKey[k] });
        out.sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase()));
        page.seenApps = out;
    }
    onSeenJsonChanged: page._rebuildSeen()
    onPlasmaAppsChanged: page._rebuildSeen()
    // DesktopEntries scans asynchronously, so a plasmanotifyrc key read before
    // the scan lands has no pretty name yet; rebuild when the scan fills in.
    onInstalledChanged: page._rebuildSeen()
    Component.onCompleted: page._rebuildSeen()

    // ---- the picker ----------------------------------------------------------
    // Installed programs matching what is typed, minus the ones already listed.
    // Capped, because a one-letter search matches most of the menu and this is
    // a list inside a scrolling page, not a launcher.
    property string appQuery: ""
    readonly property int maxMatches: 6
    readonly property var matches: {
        const q = page.appQuery.trim().toLowerCase();
        if (q.length < 2)
            return [];
        const have = {};
        for (const a of page.seenApps) have[a.key] = true;
        const out = [];
        for (const e of page.installed) {
            if (!e || e.noDisplay)
                continue;
            const id = (e.id || "").toLowerCase();
            const name = e.name || id;
            if (!id || have[id])
                continue;
            if (id.indexOf(q) < 0 && name.toLowerCase().indexOf(q) < 0)
                continue;
            out.push({ key: id, label: name });
            if (out.length >= page.maxMatches)
                break;
        }
        return out;
    }

    // Adding an app is adding it to the KNOWN list, not writing a rule: the row
    // appears with the inherited defaults and every switch still reads as
    // default until you move one.
    function addApp(key, label) {
        const seen = page.d.notifSeen || {};
        const next = {};
        for (const k in seen) next[k] = seen[k];
        next[key] = label || key;
        page.d.notifSeen = next;
        SettingsStore.save();
        page.appQuery = "";
        appSearch.clear();
    }

    // Timed do-not-disturb. The picker's value is the stored duration; arming
    // it stamps the instant the server actually obeys.
    readonly property var dndMins: ({ "off": 0, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "8h": 480 })
    function _dndLabel() {
        const m = page.d.notifDndFor;
        for (const k in page.dndMins) if (page.dndMins[k] === m) return k;
        return "off";
    }
    function _setDnd(optionLabel) {
        const mins = page.dndMins[optionLabel] || 0;
        page.d.notifDndFor = mins;
        page.d.notifDndUntil = mins > 0 ? Date.now() + mins * 60000 : 0;
        SettingsStore.save();
    }
    // What the armed timer says, refreshed on its own clock so the row does not
    // sit claiming "lifts in 1h" for the whole hour.
    property double now: Date.now()
    Timer {
        interval: 30000
        repeat: true
        running: page.d.notifDndUntil > 0
        onTriggered: page.now = Date.now()
    }
    function _dndRemaining() {
        const left = page.d.notifDndUntil - page.now;
        if (page.d.notifDndUntil <= 0 || left <= 0)
            return "";
        const mins = Math.ceil(left / 60000);
        return mins >= 60
            ? "quiet for another " + Math.floor(mins / 60) + "h " + (mins % 60) + "m"
            : "quiet for another " + mins + "m";
    }

    SetSection {
        title: "notifications"
        SetRow {
            label: "auto-dismiss after"
            desc: "critical toasts always stay until clicked"
            SetSlider {
                from: 1000; to: 15000; step: 500; unit: "ms"
                value: page.d.notifTimeoutMs
                onMoved: (v) => { page.d.notifTimeoutMs = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "max on screen"
            SetSlider {
                from: 1; to: 8; step: 1
                value: page.d.notifMaxVisible
                onMoved: (v) => { page.d.notifMaxVisible = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "toast width"
            SetSlider {
                from: 220; to: 480; step: 10; unit: "px"
                value: page.d.notifWidth
                onMoved: (v) => { page.d.notifWidth = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "corner"
            SetSelect {
                options: ["bottom-right", "bottom-left", "top-right", "top-left"]
                value: page.d.notifCorner
                onChanged: (v) => { page.d.notifCorner = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "low priority popups"
            desc: "urgency 0 - a background job's chatter"
            SetToggle {
                checked: page.d.notifLowPopup
                onToggled: (v) => { page.d.notifLowPopup = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "show images"
            desc: "advertise image support to apps"
            SetToggle {
                checked: page.d.notifImages
                onToggled: (v) => { page.d.notifImages = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "enable actions"
            desc: "advertise action buttons to apps"
            SetToggle {
                checked: page.d.notifActions
                onToggled: (v) => { page.d.notifActions = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "do not disturb"
        SetRow {
            label: "do not disturb"
            desc: "suppress toasts until you turn this back off"
            SetToggle {
                checked: page.d.doNotDisturb
                onToggled: (v) => { page.d.doNotDisturb = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "for a while"
            desc: page._dndRemaining()
            SetSelect {
                options: ["off", "15m", "30m", "1h", "2h", "4h", "8h"]
                value: page._dndLabel()
                onChanged: (v) => page._setDnd(v)
            }
        }
        SetRow {
            label: "while fullscreen"
            desc: "quiet for as long as a fullscreen window is up"
            SetToggle {
                checked: page.d.notifDndFullscreen
                onToggled: (v) => { page.d.notifDndFullscreen = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "let critical through"
            desc: "urgency 2 ignores do not disturb"
            SetToggle {
                checked: page.d.notifCriticalInDnd
                onToggled: (v) => { page.d.notifCriticalInDnd = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "mute notification sound"
            desc: "keep the toast, drop the chime"
            SetToggle {
                checked: page.d.notifSoundMute
                onToggled: (v) => { page.d.notifSoundMute = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "per-app"

        // The default every unlisted sender inherits — Plasma's "@other"
        // ("Other Applications") row, which serves the same purpose there.
        SetNotifApp {
            appKey: "@other"
            label: "all other senders"
            isDefault: true
        }

        Repeater {
            model: page.seenApps
            SetNotifApp {
                appKey: modelData.key
                label: modelData.label
            }
        }

        // Anything not listed: search the installed programs and add it, so a
        // rule can be set BEFORE the app has ever interrupted you.
        SetRow {
            label: "add an app"
            desc: "any installed program - it does not have to have notified yet"
            SetTextField {
                id: appSearch
                fieldWidth: 180
                placeholder: "search"
                // A filter narrows as you type; `committed` (Enter / focus-out)
                // is the wrong clock for it, so this is the one field that
                // reads liveText.
                onLiveTextChanged: page.appQuery = liveText
                onCommitted: (t) => {
                    // Enter takes the first match, so the whole thing is
                    // keyboard-reachable without aiming at a row.
                    if (page.matches.length > 0)
                        page.addApp(page.matches[0].key, page.matches[0].label);
                }
            }
        }

        // The matches, indented under the field they came from — the same
        // subordination the app rows use for their own switches (§9.1).
        Repeater {
            model: page.matches
            Rectangle {
                required property var modelData
                width: parent ? parent.width : 0
                height: 24
                color: mma.containsMouse ? Theme.bgAlt : "transparent"
                Rectangle {
                    anchors { left: parent.left; leftMargin: 12; top: parent.top; bottom: parent.bottom }
                    width: 1
                    color: Theme.border
                }
                PixelText {
                    anchors {
                        left: parent.left; leftMargin: 20
                        right: idText.left; rightMargin: 8
                        verticalCenter: parent.verticalCenter
                    }
                    text: modelData.label
                    color: Theme.text
                    elide: Text.ElideRight
                }
                // The id as well as the name: it is what the rule is keyed on,
                // and two installed entries can carry one display name.
                PixelText {
                    id: idText
                    anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                    text: modelData.key
                    color: Theme.textDim
                }
                MouseArea {
                    id: mma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: page.addApp(modelData.key, modelData.label)
                }
            }
        }

        PixelText {
            visible: page.appQuery.trim().length >= 2 && page.matches.length === 0
            width: parent.width
            color: Theme.textDim
            text: "no installed program matches - or it is already in the list above"
        }
    }

    SetSection {
        title: "sounds"
        SetRow {
            label: "system sounds"
            SetToggle {
                checked: page.d.soundsEnabled
                onToggled: (v) => { page.d.soundsEnabled = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "sound theme"
            desc: "folder under ~/.local/share/sounds"
            SetTextField {
                fieldWidth: 140
                value: page.d.soundTheme
                onCommitted: (t) => { page.d.soundTheme = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "login"
            SetTextField {
                fieldWidth: 200
                value: page.d.soundLogin
                onCommitted: (t) => { page.d.soundLogin = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "volume change"
            SetTextField {
                fieldWidth: 200
                value: page.d.soundVolume
                onCommitted: (t) => { page.d.soundVolume = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "notification"
            SetTextField {
                fieldWidth: 200
                value: page.d.soundNotify
                onCommitted: (t) => { page.d.soundNotify = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "critical notification"
            SetTextField {
                fieldWidth: 200
                value: page.d.soundCritical
                onCommitted: (t) => { page.d.soundCritical = t; SettingsStore.save(); }
            }
        }
    }
}
