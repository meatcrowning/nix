pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

// Weather for Juneau, AK via open-meteo (free, no key). Polled every 20
// minutes with curl. The panel shows it text-only, matching the bar's
// no-icons ethos: the CONDITION is the dim label ("rain", "snow", "clr"...)
// and the value is the temperature — the word itself is the icon.
// WeatherPanel.qml renders the 7-day forecast from `days` on hover.
Singleton {
    id: root

    readonly property string url:
        "https://api.open-meteo.com/v1/forecast?latitude=" + SettingsStore.d.weatherLat +
        "&longitude=" + SettingsStore.d.weatherLon +
        "&current_weather=true" +
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,weather_code" +
        // Hourly is what makes a morning/night reading possible at all: the
        // daily block only has a max and a min, and neither is tied to a time of
        // day. We pull the whole hourly series and sample two hours out of each
        // day (see `slots`), which is also why forecast_days is 10 rather than
        // the API's default 7.
        "&hourly=temperature_2m,weather_code,precipitation_probability" +
        "&temperature_unit=" + (SettingsStore.d.weatherUnit === "C" ? "celsius" : "fahrenheit") +
        "&precipitation_unit=" + (SettingsStore.d.weatherUnit === "C" ? "mm" : "inch") +
        "&windspeed_unit=" + (SettingsStore.d.weatherUnit === "C" ? "kmh" : "mph") +
        "&timezone=auto&forecast_days=10"

    property int tempF: -999
    property string cond: "--"
    property real windSpeed: -1
    property int windDir: -1          // degrees the wind is coming FROM
    property var days: [] // [{name, hi, lo, precip, prob, cond}]
    // Two samples per day for 10 days: [{day, name, part:"am"|"pm", temp, cond,
    // prob}]. The forecast graph in WeatherContent plots this.
    property var slots: []

    // 8-point compass name for windDir. Meteorological convention: the
    // direction the wind blows FROM, so 0 = a north wind.
    readonly property string windName: {
        if (windDir < 0) return "";
        const pts = ["n", "ne", "e", "se", "s", "sw", "w", "nw"];
        return pts[Math.round(windDir / 45) % 8];
    }
    // The hours sampled as "morning" and "night".
    readonly property int amHour: 9
    readonly property int pmHour: 21

    function refetch() { fetchProc.running = false; fetchProc.running = true; }

    // ---- retry on failure ------------------------------------------------
    // The refresh cadence is 20 minutes, so a SINGLE failed fetch used to
    // blank the widget for the next 20 — and the fetch that fails is almost
    // always the one at startup: the panel is (re)started by a rebuild, whose
    // activation restarts NetworkManager/avahi underneath it, so curl runs
    // with no DNS and exits non-zero. Same story for a login before the link
    // is up, or a wifi blip. So a failure schedules its own retry on a short
    // backoff (15s, doubling to 4min) instead of waiting for the next tick.
    property int retryMs: 15000
    function failed() {
        retryTimer.interval = root.retryMs;
        retryTimer.restart();
        root.retryMs = Math.min(root.retryMs * 2, 240000);
    }
    function succeeded() { retryTimer.stop(); root.retryMs = 15000; }

    Timer {
        id: retryTimer
        repeat: false
        onTriggered: root.refetch()
    }

    // ---- reload continuity (see shell.qml's `persist` block) --------------
    // The forecast is a 20-minute-cadence network fetch, so without this a
    // reload collapses WeatherPanel to its header for however long curl takes
    // — and the panel is bottom-anchored, so its whole card visibly grows back
    // up the screen. Carried across the reload, it's simply already there.
    property int stateRev: 0
    function stateJson() {
        return JSON.stringify({ t: tempF, c: cond, d: days, s: slots,
                                ws: windSpeed, wd: windDir });
    }
    function restoreState(s) {
        if (!s) return;
        try {
            const d = JSON.parse(s);
            root.tempF = d.t; root.cond = d.c; root.days = d.d || [];
            root.slots = d.s || [];
            root.windSpeed = d.ws === undefined ? -1 : d.ws;
            root.windDir = d.wd === undefined ? -1 : d.wd;
        } catch (e) {}
    }

    // Re-fetch immediately when the location or unit changes in Settings,
    // instead of waiting for the next refresh tick (url is a live binding, but
    // the curl Process must be re-run for the new url to take effect).
    Connections {
        target: SettingsStore.d
        function onWeatherLatChanged()  { root.refetch(); }
        function onWeatherLonChanged()  { root.refetch(); }
        function onWeatherUnitChanged() { root.refetch(); }
    }

    // WMO weather codes -> short lowercase words that fit the pixel column
    function condName(code) {
        if (code === 0) return "clr";
        if (code <= 2) return "pcld";
        if (code === 3) return "ovc";
        if (code === 45 || code === 48) return "fog";
        if (code <= 57) return "drzl";
        if (code <= 67) return "rain";
        if (code <= 77) return "snow";
        if (code <= 82) return "shwr";
        if (code <= 86) return "snow";
        return "storm";
    }

    Process {
        id: fetchProc
        command: ["curl", "-sf", "--max-time", "15", root.url]
        // curl exits non-zero on a DNS/connect/HTTP error and prints nothing
        // (-sf), so this is where a dead network is seen. onStreamFinished has
        // already run by then, so a successful parse has cleared the backoff.
        onExited: (code, status) => { if (code !== 0) root.failed(); }
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const j = JSON.parse(this.text);
                    root.tempF = Math.round(j.current_weather.temperature);
                    root.cond = root.condName(j.current_weather.weathercode);
                    root.windSpeed = j.current_weather.windspeed;
                    root.windDir = Math.round(j.current_weather.winddirection);
                    const d = j.daily;
                    let out = [];
                    for (let i = 0; i < d.time.length; i++) {
                        const dt = new Date(d.time[i] + "T12:00:00");
                        out.push({
                            name: Qt.formatDate(dt, "ddd").toLowerCase(),
                            hi: Math.round(d.temperature_2m_max[i]),
                            lo: Math.round(d.temperature_2m_min[i]),
                            precip: d.precipitation_sum[i],
                            prob: d.precipitation_probability_max ? d.precipitation_probability_max[i] : -1,
                            cond: root.condName(d.weather_code[i]),
                        });
                    }
                    root.days = out;

                    // Morning/night samples. The hourly series is a flat list of
                    // ISO local timestamps, so index by matching the date and
                    // hour rather than assuming it starts at midnight today —
                    // it does, but a DST changeover is exactly the kind of thing
                    // that makes an assumed stride wrong twice a year.
                    const h = j.hourly;
                    let idx = ({});
                    if (h && h.time) for (let i = 0; i < h.time.length; i++) idx[h.time[i]] = i;
                    let sl = [];
                    for (let i = 0; i < d.time.length; i++) {
                        const day = d.time[i];
                        const dt = new Date(day + "T12:00:00");
                        const nm = Qt.formatDate(dt, "ddd").toLowerCase();
                        for (const part of ["am", "pm"]) {
                            const hh = part === "am" ? root.amHour : root.pmHour;
                            const key = day + "T" + (hh < 10 ? "0" : "") + hh + ":00";
                            const k = idx[key];
                            if (k === undefined) continue;
                            sl.push({
                                day: day, name: nm, part: part,
                                temp: Math.round(h.temperature_2m[k]),
                                cond: root.condName(h.weather_code[k]),
                                prob: h.precipitation_probability
                                    ? h.precipitation_probability[k] : -1,
                            });
                        }
                    }
                    root.slots = sl;
                    root.stateRev++;
                    root.succeeded();
                } catch (e) {
                    // keep the last good values; "--" only before first fetch
                    root.failed();
                }
            }
        }
    }

    Timer {
        interval: SettingsStore.d.weatherRefreshMin * 60 * 1000
        running: true
        repeat: true
        onTriggered: root.refetch()
    }
    Component.onCompleted: fetchProc.running = true
}
