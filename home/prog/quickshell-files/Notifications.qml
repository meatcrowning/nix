pragma Singleton
import Quickshell
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
    readonly property int timeoutMs: 5000

    // Cap how many stack at once. Extra arrivals push the oldest non-critical
    // one out so a burst can't march off the top of the screen.
    readonly property int maxVisible: 4

    // What the toasts observe.
    readonly property var model: server.trackedNotifications
    readonly property int count: server.trackedNotifications.values.length

    // We advertise a plain-text-only server, but apps send markup anyway
    // (e.g. "<b>x</b>"). Strip tags + unescape the common entities so the pixel
    // font renders clean text instead of literal angle brackets.
    function plain(s) {
        if (!s)
            return "";
        return s.replace(/<[^>]*>/g, "")
                .replace(/&amp;/g, "&")
                .replace(/&lt;/g, "<")
                .replace(/&gt;/g, ">")
                .replace(/&quot;/g, "\"")
                .replace(/&apos;/g, "'")
                .replace(/&#39;/g, "'")
                .trim();
    }

    NotificationServer {
        id: server
        keepOnReload: false

        // Only advertise what we actually render: plain-text body, nothing else.
        // (Apps use these flags to decide what to send.)
        bodySupported: true
        bodyMarkupSupported: false
        bodyHyperlinksSupported: false
        bodyImagesSupported: false
        imageSupported: false
        actionsSupported: false
        actionIconsSupported: false
        inlineReplySupported: false
        persistenceSupported: false

        onNotification: function (n) {
            n.tracked = true;

            // Vista sounds: Exclamation for critical toasts, Balloon otherwise.
            Sounds.playThrottled(n.urgency === 2 ? "Windows Exclamation.wav" : "Windows Balloon.wav", 300);

            // Enforce maxVisible: retire the oldest non-critical toast (lowest
            // id == earliest). If everything on screen is critical, drop the
            // oldest regardless so we never grow without bound.
            const vals = server.trackedNotifications.values;
            if (vals.length > root.maxVisible) {
                let victim = null;
                for (let i = 0; i < vals.length; i++) {
                    const v = vals[i];
                    if (v === n || v.urgency === 2)
                        continue;
                    if (!victim || v.id < victim.id)
                        victim = v;
                }
                (victim || vals[0]).expire();
            }
        }
    }
}
