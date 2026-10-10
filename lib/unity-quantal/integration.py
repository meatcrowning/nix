"""Host data adapters for the original desktop; no shared preference writes."""

import configparser
import copy
import html
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET


def parser(path):
    result = configparser.ConfigParser(interpolation=None, strict=False)
    result.optionxform = str
    result.read(path, encoding="utf-8")
    return result


def settings_entries(directory, root, config, runtime):
    """Keep the old overview, using its external-panel support for host tools."""
    apps = directory / "applications"
    panels = {
        "network": ("network", "Network", "HardwareSettings"),
        "sound-nua": ("sound", "Sound", "HardwareSettings"),
        "printers": ("printers", "Printers", "HardwareSettings"),
        "power": ("power", "Power", "HardwareSettings"),
        "screen": ("screen", "Screen Lock", "X-GNOME-PersonalSettings"),
        "datetime": ("datetime", "Date & Time", "X-GNOME-SystemSettings"),
    }
    for original, (command, name, category) in panels.items():
        path = apps / ("gnome-" + original + "-panel.desktop")
        data = parser(path)
        entry = data["Desktop Entry"]
        # A distinct ID is essential: an original ID loads the old panel plugin
        # in-process and ignores Exec, even if Exec points at a native tool.
        entry["X-GNOME-Settings-Panel"] = "unity-host-" + command
        entry["Exec"] = "/usr/local/bin/unity-host-launch -- " + shlex.quote(str(Path(runtime).with_name("unity-quantal-settings"))) + " " + command
        entry["Name"] = name
        entry["OnlyShowIn"] = "Unity;"
        entry["Categories"] = "Settings;X-GNOME-Settings-Panel;" + category + ";"
        for key in list(entry):
            if key.startswith("Name[") or key in ["TryExec", "NoDisplay", "Hidden", "X-Unity-Original"]:
                del entry[key]
        temporary = path.with_suffix(".tmp")
        with temporary.open("w") as stream:
            data.write(stream, space_around_delimiters=False)
        temporary.replace(path)

    # Ubuntu's clock-format panel is supplied by indicator-datetime, not GCC;
    # the old gnome-*.desktop filter omitted it entirely.
    path = apps / "indicator-datetime-preferences.desktop"
    data = parser(root / "usr/share/applications" / path.name)
    entry = data["Desktop Entry"]
    entry["Name"] = "Clock & Calendar"
    entry["Exec"] = "/usr/local/bin/unity-host-launch -- " + shlex.quote(runtime) + " /usr/bin/gnome-control-center indicator-datetime"
    entry["X-Unity-Original"] = "true"
    entry.pop("TryExec", None)
    for key in list(entry):
        if key.startswith("Name["):
            del entry[key]
    with path.open("w") as stream:
        data.write(stream, space_around_delimiters=False)

    # Its clock-format controls still work; its date setters use Ubuntu's
    # obsolete mechanism. Host Date & Time owns those controls instead.
    ui = ET.parse(root / "usr/share/indicator-datetime/datetime-dialog.ui")
    page = ui.find(".//object[@id='timeDateBox']")
    page.find("property[@name='visible']").text = "False"
    ET.SubElement(page, "property", name="no_show_all").text = "True"
    ui.write(directory / "clock.ui", encoding="utf-8", xml_declaration=True)


def host_icons(directory, state, config):
    """Resolve host icons once and rasterize SVGs for the 2012 SVG loader."""
    legacy = Path(state["data_home"]) / "unity-quantal-session"
    output = legacy / "icons/hicolor/96x96/apps"
    output.mkdir(parents=True, exist_ok=True)
    # A partial hicolor index would hide the original applications' other sizes.
    index = parser(Path(config["runtime"]) / "usr/share/icons/hicolor/index.theme")
    if not index.has_section("96x96/apps"):
        index["Icon Theme"]["Directories"] += ",96x96/apps"
        index["96x96/apps"] = {"Size": "96", "Type": "Fixed", "Context": "Applications"}
    with (output.parent.parent / "index.theme").open("w") as stream:
        index.write(stream, space_around_delimiters=False)
    roots = [Path(state["data_home"]), *map(Path, state["data_dirs"])]
    settings = parser(Path(state["config_home"]) / "gtk-3.0/settings.ini")
    theme = settings.get("Settings", "gtk-icon-theme-name", fallback="hicolor")
    themes = [theme, "hicolor", "breeze", "oxygen"]
    candidates = {}
    for name in themes:
        for root in roots:
            base = root / "icons" / name
            if not base.is_dir():
                continue
            for folder, dirs, files in os.walk(base, followlinks=True):
                # Prefer a useful application size; retain other sizes as fallback.
                for filename in files:
                    path = Path(folder) / filename
                    if path.suffix.lower() not in (".png", ".svg", ".xpm"):
                        continue
                    rank = (themes.index(name), 0 if any(p in path.parts for p in ["48", "64", "96", "128", "scalable", "48x48", "64x64", "96x96", "128x128"]) else 1)
                    key = path.stem
                    if key not in candidates or rank < candidates[key][0]:
                        candidates[key] = (rank, path)
    for root in roots:
        for path in (root / "pixmaps").glob("*"):
            candidates.setdefault(path.stem, ((99, 0), path))
    for desktop in (directory / "applications").glob("*.desktop"):
        data = parser(desktop)
        if not data.has_section("Desktop Entry"):
            continue
        entry = data["Desktop Entry"]
        # Original applications keep the original theme's icons.
        if entry.get("X-Unity-Original") == "true" or "/usr/local/bin/unity-host-launch" not in entry.get("Exec", ""):
            continue
        icon = entry.get("Icon", "")
        source = Path(icon) if icon.startswith("/") else candidates.get(icon, (None, None))[1]
        if not source or not source.is_file():
            continue
        target = output / (desktop.stem + (".png" if source.suffix == ".svg" else source.suffix))
        if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
            try:
                if source.suffix == ".svg":
                    subprocess.run([config["rsvg"], "-w", "96", "-h", "96", "-o", str(target), str(source)],
                                   check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    shutil.copyfile(source, target)
            except (OSError, subprocess.SubprocessError):
                continue
        entry["Icon"] = str(target)
        with desktop.open("w") as stream:
            data.write(stream, space_around_delimiters=False)


def desktop_files(directory, state):
    """Give old Nautilus executable launchers without chmodding store symlinks."""
    legacy = Path(state["data_home"]) / "unity-quantal-session"
    target = legacy / "Desktop"
    target.mkdir(parents=True, exist_ok=True)
    user_dirs = Path(state["config_home"]) / "user-dirs.dirs"
    text = user_dirs.read_text() if user_dirs.exists() else ""
    match = re.search(r'^XDG_DESKTOP_DIR="(.*)"', text, re.M)
    source = Path(match[1].replace("$HOME", str(Path.home()))) if match else Path.home() / "Desktop"
    if source != target:
        for file in source.glob("*"):
            dest = target / file.name
            if file.suffix == ".desktop":
                catalog = directory / "applications" / file.name
                if catalog.is_file():
                    shutil.copyfile(catalog, dest)
                    dest.chmod(0o755)
            elif not dest.exists() and not dest.is_symlink():
                dest.symlink_to(file)
    text = re.sub(r'^XDG_DESKTOP_DIR=.*\n?', '', text, flags=re.M)
    (directory / "user-dirs.dirs").write_text(text + f'\nXDG_DESKTOP_DIR="{target}"\n')


def host_logo(name):
    """The NixOS snowflake above the system name, laid out like UbuntuLogo.png.

    Flat fills and plain paths, because Quantal's librsvg predates the
    gradients and <use> references of nixos-icons' own SVG.
    """
    lambda_ = ("m 309.54892,-710.38827 122.19683,211.67512 -56.15706,0.5268 -32.6236,-56.8692 "
               "-32.85645,56.5653 -27.90237,-0.011 -14.29086,-24.6896 46.81047,-80.4901 "
               "-33.22946,-57.8257 z")
    arms = "".join(f'<path d="{lambda_}" fill="{"#7ebae4" if turn % 2 == 0 else "#5277c3"}" '
                   f'transform="rotate({turn * 60} 407.3 -715.8)"/>' for turn in range(6))
    # The lettering colour Ambiance-Dark gives the original wordmark.
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="190" height="145">'
            f'<g transform="translate(95 54) scale(0.2) translate(-407.3 715.8)">{arms}</g>'
            '<text x="95" y="138" text-anchor="middle" font-family="Ubuntu" font-size="26" '
            f'fill="#dfdbd2">{html.escape(name)}</text></svg>\n')


def host_details(directory, root):
    """Retain the original Details layout with facts from the actual host."""
    tree = ET.parse(root / "usr/share/gnome-control-center/ui/info.ui")
    cpu = Path("/proc/cpuinfo").read_text()
    model = re.search(r'^model name\s*:\s*(.*)', cpu, re.M)
    memory = re.search(r'^MemTotal:\s*(\d+)', Path("/proc/meminfo").read_text(), re.M)
    system = {}
    if Path("/etc/os-release").exists():
        for line in Path("/etc/os-release").read_text().splitlines():
            key, _, value = line.partition("=")
            system[key] = value.strip('"')
    graphics = []
    for path in Path("/proc/driver/nvidia/gpus").glob("*/information"):
        match = re.search(r'^Model:\s*(.*)', path.read_text(), re.M)
        if match:
            graphics.append(match[1])
    disk = shutil.disk_usage(Path.home())
    values = {
        "version_label": system.get("PRETTY_NAME", "Linux"),
        "memory_label": f"{int(memory[1]) / 1048576:.1f} GiB" if memory else "Unavailable",
        "processor_label": f"{model[1] if model else 'CPU'} · {os.cpu_count()} logical CPUs",
        "graphics_label": ", ".join(graphics) or "Host graphics driver",
        "os_type_label": "64-bit",
        "disk_label": f"{disk.total / 2**30:.1f} GiB · {disk.free / 2**30:.1f} GiB free (home filesystem)",
    }
    for parent in list(tree.iter()):
        for widget in list(parent):
            key = widget.get("id")
            if key not in values:
                continue
            hidden = copy.deepcopy(widget)
            for prop in list(hidden):
                hidden.remove(prop)
            tree.getroot().append(hidden)
            widget.set("id", "host_" + key)
            for prop in widget.findall("property"):
                if prop.get("name") in ("label", "use_markup"):
                    widget.remove(prop)
            label = ET.Element("property", name="label")
            label.text = values[key]
            widget.insert(0, label)
    # The host's logo in place of the Ubuntu one, at the original artwork's
    # size. The session directory is inside the sandbox's XDG_RUNTIME_DIR.
    logo = directory / "host-logo.svg"
    logo.write_text(host_logo(system.get("NAME", "Linux")))
    tree.find(".//object[@id='system_image']/property[@name='pixbuf']").text = str(logo)
    # NixOS updates are managed by rebuild-top, not the obsolete Ubuntu updater.
    button = tree.find(".//object[@id='updates_button']")
    button.find("property[@name='visible']").text = "False"
    ET.SubElement(button, "property", name="no_show_all").text = "True"
    tree.write(directory / "info.ui", encoding="utf-8", xml_declaration=True)
    timezone = Path("/etc/localtime").resolve()
    zone = str(timezone).partition("/zoneinfo/")[2] or "UTC"
    (directory / "timezone").write_text(zone + "\n")


def plasma_pointer(config, config_home, selected=None):
    """Apply the selected profile to known devices, without moving the pointer."""
    choice = Path(config_home) / "unity-quantal/mouse-profile"
    if selected is not None:
        if selected not in ["unity", "plasma"]:
            raise ValueError("Mouse profile must be unity or plasma")
        choice.parent.mkdir(parents=True, exist_ok=True)
        choice.write_text(selected + "\n")
    selected = choice.read_text().strip() if choice.exists() else "plasma"
    settings = parser(Path(config_home) / "kcminputrc")
    for section in settings.sections():
        match = re.fullmatch(r'Libinput\]\[\d+\]\[\d+\]\[(.+)', section)
        if not match:
            continue
        ids = subprocess.run([config["xinput"], "list", "--id-only", match[1]],
                             text=True, capture_output=True)
        for device in ids.stdout.split():
            if not device.isdigit():
                continue
            properties = subprocess.run([config["xinput"], "list-props", device], text=True, capture_output=True).stdout
            profile = settings[section]
            changes = {}
            if "PointerAcceleration" in profile:
                changes["libinput Accel Speed"] = [str(float(profile["PointerAcceleration"]))]
            if "PointerAccelerationProfile" in profile:
                flat = profile["PointerAccelerationProfile"] == "1"
                changes["libinput Accel Profile Enabled"] = ["0", "1", "0"] if flat else ["1", "0", "0"]
            if selected == "unity":
                changes = {"libinput Accel Speed": ["0"], "libinput Accel Profile Enabled": ["1", "0", "0"]}
            for key, prop in [("NaturalScroll", "libinput Natural Scrolling Enabled"), ("LeftHanded", "libinput Left Handed Enabled")]:
                if selected == "plasma" and key in profile:
                    changes[prop] = ["1" if profile[key].lower() == "true" else "0"]
            for prop, value in changes.items():
                if prop in properties:
                    subprocess.run([config["xinput"], "set-prop", device, prop, *value], check=True)
