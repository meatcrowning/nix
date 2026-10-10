#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
"""Weather indicator for the Unity session, laid out like indicator-weather.

`indicator` runs on the original runtime's Python 2.7, GTK 3.6 and
AppIndicator. The runtime has no network, so it asks the session supervisor to
run `fetch` with the host's Python 3, which queries Open-Meteo (no account or
key) and writes a report file that the indicator follows. The location is
whatever the user types into Set Location; it stays in their config directory.
"""
from __future__ import division, print_function

import fcntl
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                        "unity-quantal", "weather.json")
# The runtime's cache home; the indicator passes this path to the fetcher.
REPORT = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "weather.json")
INTERVAL = 15 * 60
# WMO weather interpretation codes: (condition, day icon, night icon).
CODES = {
    0: ("Clear", "weather-clear", "weather-clear-night"),
    1: ("Mostly Clear", "weather-few-clouds", "weather-few-clouds-night"),
    2: ("Partly Cloudy", "weather-few-clouds", "weather-few-clouds-night"),
    3: ("Overcast", "weather-overcast", "weather-overcast"),
    45: ("Fog", "weather-fog", "weather-fog"),
    48: ("Freezing Fog", "weather-fog", "weather-fog"),
    51: ("Light Drizzle", "weather-showers-scattered", "weather-showers-scattered"),
    53: ("Drizzle", "weather-showers-scattered", "weather-showers-scattered"),
    55: ("Heavy Drizzle", "weather-showers", "weather-showers"),
    56: ("Freezing Drizzle", "weather-showers-scattered", "weather-showers-scattered"),
    57: ("Freezing Drizzle", "weather-showers", "weather-showers"),
    61: ("Light Rain", "weather-showers-scattered", "weather-showers-scattered"),
    63: ("Rain", "weather-showers", "weather-showers"),
    65: ("Heavy Rain", "weather-showers", "weather-showers"),
    66: ("Freezing Rain", "weather-showers", "weather-showers"),
    67: ("Freezing Rain", "weather-showers", "weather-showers"),
    71: ("Light Snow", "weather-snow", "weather-snow"),
    73: ("Snow", "weather-snow", "weather-snow"),
    75: ("Heavy Snow", "weather-snow", "weather-snow"),
    77: ("Snow Grains", "weather-snow", "weather-snow"),
    80: ("Rain Showers", "weather-showers-scattered", "weather-showers-scattered"),
    81: ("Rain Showers", "weather-showers", "weather-showers"),
    82: ("Violent Rain Showers", "weather-showers", "weather-showers"),
    85: ("Snow Showers", "weather-snow", "weather-snow"),
    86: ("Heavy Snow Showers", "weather-snow", "weather-snow"),
    95: ("Thunderstorm", "weather-storm", "weather-storm"),
    96: ("Thunderstorm with Hail", "weather-storm", "weather-storm"),
    99: ("Thunderstorm with Hail", "weather-storm", "weather-storm"),
}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def read_json(path):
    try:
        with open(path) as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def write_json(path, data):
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    temporary = path + ".tmp"
    with open(temporary, "w") as stream:
        json.dump(data, stream, sort_keys=True)
    os.rename(temporary, path)


def imperial_locale():
    for key in ("LC_ALL", "LC_MEASUREMENT", "LANG"):
        value = os.environ.get(key)
        if value:
            return value.split(".")[0] in ("en_US", "es_US", "en_LR", "my_MM")
    return False


# The fetcher: host Python 3, standard library only.

def get(url, parameters):
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    request = Request(url + "?" + urlencode(parameters), headers={"User-Agent": "unity-quantal-weather"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def geocode(query):
    """Match "City" or "City, Region, Country" against Open-Meteo's place names."""
    parts = [part.strip() for part in query.split(",") if part.strip()]
    name, qualifiers = parts[0], parts[1:]
    results = get("https://geocoding-api.open-meteo.com/v1/search",
                  {"name": name, "count": 20, "language": "en", "format": "json"}).get("results") or []
    for place in results:
        fields = [str(place.get(key, "")).lower() for key in ("admin1", "admin2", "country", "country_code")]
        if all(any(field.startswith(q.lower()) for field in fields) for q in qualifiers):
            region = place.get("admin1") if place.get("admin1") != place.get("name") else None
            return {"name": ", ".join(p for p in (place["name"], region, place.get("country")) if p),
                    "latitude": place["latitude"], "longitude": place["longitude"]}
    return None


def fetch(settings_path, report_path):
    lock = open(report_path + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    query = str(read_json(settings_path).get("location", "")).strip()
    previous = read_json(report_path)
    report = {"query": query, "fetched": time.time()}
    if not query:
        write_json(report_path, report)
        return
    try:
        place = previous.get("place") if previous.get("query") == query else None
        place = place or geocode(query)
        if place is None:
            report["error"] = "No place found for “" + query + "”"
            write_json(report_path, report)
            return
        report["place"] = place
        report["forecast"] = get("https://api.open-meteo.com/v1/forecast", {
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
            "forecast_days": 5, "wind_speed_unit": "kmh",
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
                       "wind_speed_10m,wind_direction_10m,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset"})
    except (OSError, ValueError, KeyError) as error:
        print("weather: " + str(error), file=sys.stderr)
        # Keep the last good report on screen, marked as out of date.
        if previous.get("query") == query and previous.get("forecast"):
            report = dict(previous, fetched=time.time())
        report["error"] = "Weather service unavailable"
    write_json(report_path, report)


# The indicator: original runtime Python 2.7.

def indicator():
    from gi.repository import AppIndicator3, Gio, GLib, GObject, Gtk

    with open(os.path.join(HERE, "config.json")) as stream:
        host_python = json.load(stream)["python"]

    class Indicator(Gtk.Application):
        def __init__(self):
            Gtk.Application.__init__(self, application_id="org.unity_quantal.Weather",
                                     flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.started = False
            self.dialog = None
            self.requested = 0

        def do_activate(self):
            if self.started:
                return
            self.started = True
            self.hold()
            self.indicator = AppIndicator3.Indicator.new(
                "unity-quantal-weather", "weather-few-clouds", AppIndicator3.IndicatorCategory.OTHER)
            self.indicator.set_title("Weather")
            menu = Gtk.Menu()

            def line():
                item = Gtk.MenuItem("")
                item.set_sensitive(False)
                menu.append(item)
                return item
            self.place = line()
            self.condition = line()
            menu.append(Gtk.SeparatorMenuItem())
            self.details = [line() for _ in range(6)]
            self.forecast_separator = Gtk.SeparatorMenuItem()
            menu.append(self.forecast_separator)
            self.forecast_item = Gtk.MenuItem("Forecast")
            self.forecast = Gtk.Menu()
            self.forecast_item.set_submenu(self.forecast)
            menu.append(self.forecast_item)
            menu.append(Gtk.SeparatorMenuItem())
            self.refresh = Gtk.MenuItem("Refresh")
            self.refresh.connect("activate", lambda *_: self.request())
            menu.append(self.refresh)
            self.units = {}
            for units, label in (("metric", "Celsius"), ("imperial", "Fahrenheit")):
                item = Gtk.CheckMenuItem(label)
                item.set_draw_as_radio(True)
                item.connect("activate", self.choose_units, units)
                menu.append(item)
                self.units[units] = item
            locate = Gtk.MenuItem(u"Set Location…")
            locate.connect("activate", self.locate)
            menu.append(locate)
            menu.show_all()
            self.updating = False
            self.indicator.set_menu(menu)
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

            self.monitors = [self.watch(SETTINGS), self.watch(REPORT)]
            self.show()
            self.tick()
            # Wall-clock check, so a resume from suspend refreshes promptly.
            GLib.timeout_add_seconds(60, self.tick)

        def watch(self, path):
            directory = os.path.dirname(path)
            if not os.path.isdir(directory):
                os.makedirs(directory)
            monitor = Gio.File.new_for_path(directory).monitor_directory(Gio.FileMonitorFlags.NONE, None)

            def changed(_monitor, file, _other, event):
                if file.get_path() == path and event != Gio.FileMonitorEvent.DELETED:
                    self.show()
                    if path == SETTINGS:
                        self.tick()
            monitor.connect("changed", changed)
            return monitor

        def settings(self):
            settings = read_json(SETTINGS)
            if settings.get("units") not in ("metric", "imperial"):
                settings["units"] = "imperial" if imperial_locale() else "metric"
            return settings

        def tick(self):
            settings, report = self.settings(), read_json(REPORT)
            query = str(settings.get("location", "")).strip()
            stale = report.get("query") != query or time.time() - report.get("fetched", 0) >= INTERVAL
            if query and stale and time.time() - self.requested >= 60:
                self.request()
            return True

        def request(self):
            self.requested = time.time()
            try:
                subprocess.Popen(["/usr/local/bin/unity-host-launch", "--", host_python,
                                  os.path.abspath(__file__), "fetch", SETTINGS, REPORT])
            except OSError as error:
                print("weather: cannot start the fetcher: " + str(error), file=sys.stderr)

        def show(self):
            settings, report = self.settings(), read_json(REPORT)
            imperial = settings["units"] == "imperial"
            query = str(settings.get("location", "")).strip()
            forecast = report.get("forecast") if report.get("query") == query else None

            def temperature(celsius, unit=True):
                value = celsius * 9 / 5 + 32 if imperial else celsius
                return u"%d°" % round(value) + ((u"F" if imperial else u"C") if unit else u"")

            def clock(stamp):
                hour, minute = int(stamp[11:13]), stamp[14:16]
                if imperial:
                    return "%d:%s %s" % ((hour - 1) % 12 + 1, minute, "AM" if hour < 12 else "PM")
                return "%02d:%s" % (hour, minute)

            self.updating = True
            for units, item in self.units.items():
                item.set_active(units == settings["units"])
            self.updating = False
            for item in self.forecast.get_children():
                self.forecast.remove(item)
            for item in self.details:
                item.hide()
            if not forecast:
                self.place.set_label(report.get("error") or (u"Updating…" if query else "No location set"))
                self.condition.hide()
                for item in (self.forecast_separator, self.forecast_item, self.refresh):
                    item.set_visible(bool(query))
                self.forecast_item.set_sensitive(False)
                self.indicator.set_icon("weather-severe-alert" if report.get("error") else "weather-few-clouds")
                self.indicator.set_label("", "")
                return
            current, daily = forecast["current"], forecast["daily"]
            code = CODES.get(current.get("weather_code"), ("Unknown", "weather-severe-alert", "weather-severe-alert"))
            self.indicator.set_icon(code[1] if current.get("is_day", 1) else code[2])
            self.indicator.set_label(temperature(current["temperature_2m"], False), u"-88°")
            self.place.set_label(report["place"]["name"])
            self.condition.set_label(code[0])
            self.condition.show()
            wind = current["wind_speed_10m"]
            lines = [
                "Temperature: " + temperature(current["temperature_2m"]),
                "Feels like: " + temperature(current["apparent_temperature"]),
                "Humidity: %d%%" % round(current["relative_humidity_2m"]),
                "Wind: %s at %d %s" % (COMPASS[int((current["wind_direction_10m"] + 22.5) // 45) % 8],
                                        round(wind / 1.609344 if imperial else wind), "mph" if imperial else "km/h"),
                "Sunrise: " + clock(daily["sunrise"][0]),
                "Sunset: " + clock(daily["sunset"][0]),
            ]
            for item, text in zip(self.details, lines):
                item.set_label(text)
                item.show()
            for index, day in enumerate(daily["time"]):
                name = "Today" if index == 0 else time.strftime("%A", time.strptime(day, "%Y-%m-%d"))
                text = u"%s: %s, %s / %s" % (name, CODES.get(daily["weather_code"][index], ("Unknown",))[0],
                                             temperature(daily["temperature_2m_max"][index]),
                                             temperature(daily["temperature_2m_min"][index]))
                item = Gtk.MenuItem(text)
                item.set_sensitive(False)
                item.show()
                self.forecast.append(item)
            for item in (self.forecast_separator, self.forecast_item, self.refresh):
                item.show()
            self.forecast_item.set_sensitive(True)
            updated = time.strftime("%H:%M", time.localtime(report.get("fetched", time.time())))
            self.refresh.set_label(("Out of date, refresh" if report.get("error") else "Refresh") +
                                   " (updated " + updated + ")")

        def choose_units(self, item, units):
            if self.updating:
                return
            if not item.get_active():
                # Re-picking the current unit leaves it selected.
                self.show()
                return
            settings = read_json(SETTINGS)
            settings["units"] = units
            write_json(SETTINGS, settings)

        def locate(self, *_arguments):
            if self.dialog:
                self.dialog.present()
                return
            dialog = self.dialog = Gtk.Dialog("Weather Location", None, 0,
                                              (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                               Gtk.STOCK_OK, Gtk.ResponseType.OK))
            dialog.set_default_response(Gtk.ResponseType.OK)
            dialog.set_resizable(False)
            dialog.set_icon_name("weather-few-clouds")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_border_width(12)
            label = Gtk.Label(u"Enter a city, optionally with its region or country:")
            label.set_alignment(0, 0.5)
            entry = Gtk.Entry()
            entry.set_text(str(read_json(SETTINGS).get("location", "")))
            entry.set_activates_default(True)
            entry.set_size_request(320, -1)
            box.pack_start(label, False, False, 0)
            box.pack_start(entry, False, False, 0)
            dialog.get_content_area().pack_start(box, True, True, 0)

            def respond(_dialog, response):
                if response == Gtk.ResponseType.OK:
                    settings = read_json(SETTINGS)
                    settings["location"] = entry.get_text().strip()
                    write_json(SETTINGS, settings)
                dialog.destroy()
                self.dialog = None
            dialog.connect("response", respond)
            dialog.show_all()
            dialog.present()

    GLib.set_prgname("unity-weather")
    GObject.threads_init()
    return Indicator().run(sys.argv[:1])


if __name__ == "__main__":
    if sys.argv[1:2] == ["fetch"] and len(sys.argv) == 4:
        fetch(sys.argv[2], sys.argv[3])
    elif sys.argv[1:] == ["indicator"]:
        sys.exit(indicator())
    else:
        raise SystemExit("usage: weather.py indicator | fetch SETTINGS REPORT")
