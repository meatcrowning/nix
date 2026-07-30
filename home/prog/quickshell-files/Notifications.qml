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
        // else has to be asked for by name. These two are how a KDE Connect
        // toast names the phone it came from — see "who a toast is FROM" above.
        extraHints: ["x-kde-origin-name", "x-kdeconnect-source-device"]

        onNotification: function (n) {
            // Do Not Disturb: suppress toasts, but let critical (urgency 2)
            // through — standard DND behaviour.
            if (SettingsStore.d.doNotDisturb && n.urgency !== 2)
                return;

            n.tracked = true;

            // Vista sounds: critical vs. normal, both user-configurable.
            Sounds.playThrottled(n.urgency === 2 ? SettingsStore.d.soundCritical : SettingsStore.d.soundNotify, 300);

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
