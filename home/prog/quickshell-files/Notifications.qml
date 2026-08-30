pragma Singleton
import Quickshell
import Quickshell.Io
import Quickshell.Services.Notifications
import QtQuick

// The desktop notification server. Quickshell owns org.freedesktop.Notifications
// (no dunst/mako needed); toasts are rendered by NotificationWindow.qml. This is
// a Singleton so exactly ONE server binds the bus even though the panel itself
// is instantiated per-screen — mirrors how Osd holds the shared OSD state.
Singleton {
    id: root

    // How long a non-critical toast lingers before auto-expiring (ms). Critical
    // (urgency 2) toasts never auto-expire; they stay until clicked.
    readonly property int timeoutMs: SettingsStore.d.notifTimeoutMs

    // Cap how many stack at once. Extra arrivals push the oldest non-critical
    // one out so a burst can't march off the top of the screen.
    readonly property int maxVisible: SettingsStore.d.notifMaxVisible

    // What the toasts observe.
    readonly property var model: server.trackedNotifications
    readonly property int count: server.trackedNotifications.values.length

    // We advertise a plain-text-only server, but apps send markup anyway
    // (e.g. "<b>x</b>"). Strip tags + unescape the common entities so the pixel
    // font renders clean text instead of literal angle brackets.
    //
    // Then Glyphs.px, for the other half of the same problem: what an app sends
    // is prose, and prose is full of curly quotes, ellipses and en dashes that
    // More Perfect DOS VGA has no glyph for — each of which drops the line it
    // sits on out of its row. This is the ingest point for every notification
    // the panel draws, so it is the only place that needs it.
    function plain(s) {
        if (!s)
            return "";
        return Glyphs.px(s.replace(/<[^>]*>/g, "")
                .replace(/&amp;/g, "&")
                .replace(/&lt;/g, "<")
                .replace(/&gt;/g, ">")
                .replace(/&quot;/g, "\"")
                .replace(/&apos;/g, "'")
                .replace(/&#39;/g, "'")
                .trim());
    }

    // ---- who may toast, and when ---------------------------------------------
    //
    // Modelled on Plasma's kcm_notifications / plasmanotifyrc, which splits the
    // question in two: a handful of global conditions, and a per-sender rule.
    // Ours keeps the same split and the same defaults, with two deliberate
    // divergences, both because the feature underneath does not exist here:
    // there is no notification history (so no ShowInHistory) and no taskbar
    // badge (so no ShowBadges).
    //
    // Plasma's other trick we DO take: it cannot know which apps notify, so it
    // remembers the ones that have. `Seen=true` there, `notifSeen` here — and
    // since this desktop has nothing like .desktop's X-GNOME-UsesNotifications
    // to enumerate from, that learned list IS the per-app list the Settings
    // window draws.

    // BOTH names a sender might be known by, most specific first: its desktop
    // entry, then its app name, both lowercased (neither is case-stable across
    // sends). A rule under either one matches, and that is not pedantry — the
    // two disagree constantly. Vivaldi's desktop entry is `vivaldi-stable`
    // while a rule added from the installed-apps picker is keyed on that id,
    // and this desktop's own programs send `-a filer` with no desktop entry at
    // all. Matching one name only would mean a rule that silently never fires.
    function keysFor(n) {
        if (!n)
            return ["@other"];
        const de = (n.desktopEntry || "").trim().toLowerCase();
        const an = (n.appName || "").trim().toLowerCase();
        const out = [];
        if (de)
            out.push(de);
        if (an && an !== de)
            out.push(an);
        return out.length ? out : ["@other"];
    }

    // The one key a sender is RECORDED under, when it has to be just one.
    function keyFor(n) { return root.keysFor(n)[0]; }

    // A rule holds only its divergences, so an absent field means the default.
    // A sender matching no rule inherits "@other" — the one row in the Settings
    // list that is not a real app.
    function ruleFor(n) { return root.ruleForKeys(root.keysFor(n)); }
    function ruleForKeys(keys) {
        const rules = SettingsStore.d.notifRules || {};
        let r = null;
        for (const k of keys)
            if (rules[k]) { r = rules[k]; break; }
        if (!r)
            r = rules["@other"] || {};
        return {
            popup: r.popup !== false,
            dnd: r.dnd === true,
            sound: r.sound !== false
        };
    }

    // Is do-not-disturb in force right now? Deliberately a function, not a
    // property: `notifDndUntil` is a wall-clock instant and a binding over
    // Date.now() would never re-evaluate. Everything that asks, asks at the
    // moment a notification arrives.
    function dndNow() {
        const d = SettingsStore.d;
        if (d.doNotDisturb)
            return true;
        if (d.notifDndUntil > 0 && Date.now() < d.notifDndUntil)
            return true;
        return d.notifDndFullscreen && WinState.fullscreenShown;
    }

    // Retire an expired timed DND, so the Settings window is never left showing
    // a "until 14:30" that lapsed an hour ago. A minute's granularity is enough
    // for a control whose shortest step is 15 minutes; dndNow() is exact
    // regardless, so a late tick can never suppress a toast it should not.
    Timer {
        interval: 60000
        repeat: true
        running: true
        onTriggered: {
            const until = SettingsStore.d.notifDndUntil;
            if (until > 0 && Date.now() >= until) {
                SettingsStore.d.notifDndUntil = 0;
                SettingsStore.d.notifDndFor = 0;
                SettingsStore.save();
            }
        }
    }

    // Remember a sender the first time it toasts. Only the first time: the
    // display name is not re-recorded on every notification, both to keep the
    // panel off the disk in a burst and because the name a rule was made under
    // should not shift under it. Capped so a runaway sender inventing a new
    // app name per notification cannot grow settings.json without bound.
    readonly property int maxSeen: 200
    function _recordSeen(n) {
        const key = root.keyFor(n);
        const seen = SettingsStore.d.notifSeen || {};
        if (seen[key] !== undefined)
            return;
        let count = 0;
        const next = {};
        for (const k in seen) { next[k] = seen[k]; count++; }
        if (count >= root.maxSeen)
            return;
        next[key] = (n.appName || key);
        // Reassigned wholesale, never mutated in place: SettingsStore diffs by
        // JSON.stringify against its last-seen-on-disk snapshot, and an
        // in-place edit of the object it handed back changes both sides.
        SettingsStore.d.notifSeen = next;
        SettingsStore.save();
    }

    // ---- who a toast is FROM -------------------------------------------------
    //
    // Every notification his phone relays arrives with appName "KDE Connect" —
    // the same string for all of them, and useless as a header when the phone's
    // own name is right there in the hints. So KDE Connect toasts are titled
    // with the DEVICE; nothing else changes.
    //
    // The channel was measured, not assumed. kdeconnect's notifications plugin
    // (kdeconnect_notifications.so, Notification::createKNotification) calls
    // KNotification::setHint twice with Device::name() as the value —
    // `x-kde-origin-name` and `x-kdeconnect-source-device` — plus
    // `x-kde-display-appname` for the phone-side app. knotifications forwards
    // every hint a KNotification carries verbatim into the freedesktop `Notify`
    // call (an unconditional loop over KNotification::hints() in
    // NotifyByPopup::sendNotificationToServer), so all three reach us; the
    // server's advertised capabilities do not filter them.
    //
    // Quickshell parses only the hints it knows about, so the two we want have
    // to be named in `extraHints` below or `Notification.hints` never holds them.

    // Paired devices, id -> name AND name -> name, from kdeconnect-cli. Only a
    // FALLBACK: `x-kdeconnect-source-device` is documented upstream as the
    // device ID, and this build happens to put the name there, so a build that
    // sends an id must still be able to name the phone. Reassigned wholesale
    // (never mutated) so bindings that called sender() re-evaluate when it lands.
    property var kdeDevices: ({})

    // What the card's header line says. The app's own name, except for a KDE
    // Connect relay that can name its phone.
    function sender(n) {
        if (!n)
            return "notification";
        const dev = root.device(n);
        if (dev)
            return dev;
        return n.appName ? Glyphs.px(n.appName) : "notification";
    }

    // The phone a KDE Connect notification came from, or "" for everything else
    // — including a KDE Connect toast whose device cannot be named, which keeps
    // the plain appName rather than showing something blank or wrong.
    function device(n) {
        const h = n ? n.hints : null;
        if (!h)
            return "";

        // Identify KDE Connect first: `x-kde-origin-name` is a general KDE hint
        // (accounts, bridges), and only KDE Connect's title may be replaced.
        const src = h["x-kdeconnect-source-device"];
        if (src === undefined && !root._isKdeConnect(n))
            return "";

        let cand = (h["x-kde-origin-name"] || "").toString();
        if (!cand)
            cand = (src || "").toString();
        if (!cand)
            return "";

        const known = root.kdeDevices[cand];
        if (known)
            return root.plain(known);
        if (root._looksLikeDeviceId(cand)) {
            // An opaque id is worse than the app name. Ask kdeconnect for the
            // table and leave the header alone until it answers.
            root._resolveDevices();
            return "";
        }
        return root.plain(cand);
    }

    function _isKdeConnect(n) {
        const app = (n.appName || "").toLowerCase().replace(" ", "");
        const de = (n.desktopEntry || "").toLowerCase();
        return app === "kdeconnect" || de.indexOf("kdeconnect") >= 0;
    }

    // Both id forms kdeconnect issues are hex with separators — a 32-char digest
    // (`05624379b7504dd0905e92bcdb271284`) or an underscored UUID
    // (`f0c292e9_700f_4b76_8ddb_4dadc3e04307`). The length floor is what keeps a
    // short real phone name out of it.
    function _looksLikeDeviceId(s) {
        return s.length >= 16 && /^[0-9a-fA-F_-]+$/.test(s);
    }

    function _resolveDevices() {
        if (devices.running)
            return;
        // Throttle: a stream of notifications from an unknown id must not spawn
        // a process each.
        const now = Date.now();
        if (now - root._lastResolve < 60000)
            return;
        root._lastResolve = now;
        devices.running = true;
    }

    property double _lastResolve: -60000

    // kdeconnect-cli is nix-only, so it needs NixPath's prologue to resolve on
    // book. The two lists come from one walk of the same device list on
    // kdeconnect's side, so they line up by index — a mismatch is refused
    // outright rather than zipped into wrong names.
    Process {
        id: devices
        command: ["sh", "-c", NixPath.sh
            + "kdeconnect-cli --list-devices --id-only; echo '--'; "
            + "kdeconnect-cli --list-devices --name-only"]
        stdout: StdioCollector {
            onStreamFinished: {
                const parts = this.text.split("\n--\n");
                if (parts.length !== 2)
                    return;
                const ids = parts[0].split("\n").filter(s => s.length > 0);
                const names = parts[1].split("\n").filter(s => s.length > 0);
                if (ids.length !== names.length) {
                    console.warn("Notifications: kdeconnect-cli listed "
                        + ids.length + " ids and " + names.length
                        + " names - not naming devices from it");
                    return;
                }
                const map = {};
                for (let i = 0; i < ids.length; i++) {
                    map[ids[i]] = names[i];
                    map[names[i]] = names[i];
                }
                root.kdeDevices = map;
            }
        }
    }

    NotificationServer {
        id: server
        keepOnReload: false

        // Only advertise what we actually render: plain-text body, plus
        // whatever the user has opted into. (Apps use these flags to decide
        // what to send.)
        bodySupported: true
        bodyMarkupSupported: false
        bodyHyperlinksSupported: false
        bodyImagesSupported: SettingsStore.d.notifImages
        imageSupported: SettingsStore.d.notifImages
        actionsSupported: SettingsStore.d.notifActions
        actionIconsSupported: SettingsStore.d.notifActions
        inlineReplySupported: false
        persistenceSupported: false

        // Quickshell only parses the hints it has properties for, so anything
        // else has to be asked for by name. These are how a KDE Connect toast
        // names the phone it came from — see "who a toast is FROM" above — and
        // `x-download-image`, which surfer's completion toast (and the screenshot
        // / screen-recording toasts) carry the thumbnail path in, so the card can
        // thumbnail it and open it. `x-open-path` overrides what the click opens
        // when it differs from the thumbnail (a recording: poster thumb, mp4 open).
        // `value` is the de-facto progress hint (KDE, dunst and GNOME all read
        // it; `notify-send -h int:value:37` sends it): an int 0-100 that makes
        // a toast a PROGRESS toast, drawn as the card's bar. repo-updates ships
        // it on every step of a pull-and-rebuild.
        // `x-vista-sound` names the .wav this toast should play INSTEAD of the
        // urgency default, so a sender with a sound of its own (the battery
        // alarm) does not have to choose between its own sound and a toast.
        // Still silenceable exactly like the defaults — it is played on the
        // same line, behind the same two gates.
        extraHints: ["x-kde-origin-name", "x-kdeconnect-source-device",
                     "x-download-image", "x-open-path", "value", "x-vista-sound"]

        onNotification: function (n) {
            // Learn the sender before deciding anything, so an app whose
            // popups you switched off still has a row to switch them back on.
            root._recordSeen(n);

            const rule = root.ruleFor(n);
            const critical = n.urgency === 2;

            // The sender's own rule comes first and binds even for critical:
            // "show popups: off" is an explicit choice about THAT app, and a
            // toggle a notification can talk its way past is a dishonest one.
            if (!rule.popup)
                return;

            // Urgency 0 is "you may care later" — a background sync's chatter.
            if (n.urgency === 0 && !SettingsStore.d.notifLowPopup)
                return;

            // Do Not Disturb: suppress, unless this sender is allowed through
            // it, or it is critical and criticals are allowed through (which
            // is the shipped default, and the standard behaviour).
            if (root.dndNow()
                    && !(critical ? SettingsStore.d.notifCriticalInDnd : rule.dnd))
                return;

            n.tracked = true;

            // Vista sounds: critical vs. normal, both user-configurable, and
            // both silenceable per sender or globally without losing the toast.
            if (rule.sound && !SettingsStore.d.notifSoundMute) {
                const own = String((n.hints && n.hints["x-vista-sound"]) || "").trim();
                Sounds.playThrottled(own || (critical ? SettingsStore.d.soundCritical
                                                      : SettingsStore.d.soundNotify), 300);
            }

            // Enforce maxVisible: retire the oldest expendable toast (lowest
            // id == earliest). Critical toasts and ones that asked never to
            // expire (expire_timeout 0 — a live progress bar being morphed in
            // place) are spared, since evicting one puts its sender straight
            // back into the "every update opens a new toast" loop. If
            // everything on screen is spared, drop the oldest regardless so we
            // never grow without bound.
            const vals = server.trackedNotifications.values;
            if (vals.length > root.maxVisible) {
                let victim = null;
                for (let i = 0; i < vals.length; i++) {
                    const v = vals[i];
                    if (v === n || v.urgency === 2 || v.expireTimeout === 0)
                        continue;
                    if (!victim || v.id < victim.id)
                        victim = v;
                }
                (victim || vals[0]).expire();
            }
        }
    }
}
