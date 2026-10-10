"""Unity 12.10's terminal for the Unity session.

GNOME Terminal 3.6's window as Ubuntu shipped it (menubar, tabs, scrollbar,
aubergine screen, Tango palette, Ubuntu Mono 13), drawn by GTK 3 over the
current VTE so modern programs get true colour and current escape handling.
Chrome colours are Ambiance's, as measured from the original in this session.
"""

import os
import pwd
import re
import sys

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, Vte  # noqa: E402

NAME = "unity-terminal"
FONT = "Ubuntu Mono 13"
FOREGROUND = "#ffffff"
BACKGROUND = "#300a24"
# gnome-terminal.schemas palette (Tango); the original renders colour 0 black.
PALETTE = ["#000000", "#cc0000", "#4e9a06", "#c4a000", "#3465a4", "#75507b", "#06989a", "#d3d7cf",
           "#555753", "#ef2929", "#8ae234", "#fce94f", "#729fcf", "#ad7fa8", "#34e2e2", "#eeeeec"]
# GNOME Terminal 3.6's zoom steps.
ZOOMS = [0.5787, 0.6944, 0.8333, 1.0, 1.2, 1.44, 1.728]
# New screens and Normal Size open one step out (FONT at about 10.8 points).
DEFAULT_ZOOM = ZOOMS.index(0.8333)
PCRE2_CASELESS = 0x00000008
PCRE2_MULTILINE = 0x00000400

# Ambiance's terminal chrome: dark menubar and menus, orange highlight, and the
# scrollbar and tabs as Ambiance Dark draws them (the session's theme).
CSS = """
@define-color dark_bg_color #3c3b37;
@define-color dark_fg_color #dfdbd2;
@define-color selected_bg_color #f07746;
@define-color selected_fg_color #ffffff;
@define-color bg_color #33322f;
@define-color button_bg_color shade(@bg_color, 1.02);

window.unity-terminal { background-color: @dark_bg_color; }

window.unity-terminal menubar {
    background-color: @dark_bg_color;
    background-image: none;
    border: none;
    box-shadow: none;
    padding: 0;
    color: @dark_fg_color;
    text-shadow: 0 -1px shade(@dark_bg_color, 0.6);
}
window.unity-terminal menubar > menuitem {
    padding: 2px 4px 3px 4px;
    margin: 0;
    border: 1px solid transparent;
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    color: @dark_fg_color;
}
window.unity-terminal menubar > menuitem:hover {
    border-color: shade(@dark_bg_color, 0.87);
    background-image: linear-gradient(to bottom, shade(@dark_bg_color, 1.32), shade(@dark_bg_color, 1.11));
    box-shadow: none;
    color: shade(@dark_fg_color, 1.1);
    text-shadow: 0 -1px shade(@dark_bg_color, 0.7);
}

menu, .menu, .context-menu {
    background-image: none;
    background-color: shade(@dark_bg_color, 1.08);
    border: 1px solid shade(@dark_bg_color, 0.8);
    border-top-color: shade(@dark_bg_color, 0.96);
    border-bottom-color: shade(@dark_bg_color, 0.96);
    padding: 5px 0;
    color: @dark_fg_color;
    box-shadow: inset 0 1px shade(@dark_bg_color, 1.18), inset 0 -1px shade(@dark_bg_color, 1.18),
                inset -1px 0 shade(@dark_bg_color, 1.16), inset 1px 0 shade(@dark_bg_color, 1.18);
}
menu menuitem {
    padding: 2px 11px 2px 0;
    border: 1px solid transparent;
    border-radius: 0;
    text-shadow: none;
    color: @dark_fg_color;
}
menu menuitem:hover {
    background-image: linear-gradient(to bottom, shade(@selected_bg_color, 1.1), shade(@selected_bg_color, 0.9));
    border-color: shade(@selected_bg_color, 0.7);
    box-shadow: inset 1px 0 shade(@selected_bg_color, 1.02), inset -1px 0 shade(@selected_bg_color, 1.02),
                inset 0 1px shade(@selected_bg_color, 1.16), inset 0 -1px shade(@selected_bg_color, 0.96);
    color: @selected_fg_color;
    text-shadow: 0 -1px shade(@selected_bg_color, 0.7);
}
menu menuitem:disabled, menu menuitem:disabled label {
    color: mix(@dark_fg_color, @dark_bg_color, 0.5);
    text-shadow: 0 -1px shade(@dark_bg_color, 0.6);
}
menu separator {
    margin: 3px 0 4px 0;
    min-height: 1px;
    background-color: shade(@dark_bg_color, 0.99);
    box-shadow: 0 1px alpha(shade(@dark_bg_color, 1.26), 0.5);
}
menu check, menu radio { color: @dark_fg_color; }
menu menuitem:hover check, menu menuitem:hover radio { color: @selected_fg_color; }
menu arrow { color: @dark_fg_color; }

window.unity-terminal scrollbar {
    background-color: @bg_color;
    border-left: 1px solid shade(@bg_color, 0.8);
    padding: 0;
}
window.unity-terminal scrollbar trough { background: none; border: none; }
window.unity-terminal scrollbar slider {
    min-width: 12px;
    min-height: 30px;
    margin: 0;
    border: 1px solid shade(@bg_color, 0.86);
    border-radius: 20px;
    background-color: @button_bg_color;
    background-image: linear-gradient(to right, shade(@button_bg_color, 1.08), @button_bg_color, shade(@button_bg_color, 0.94));
    box-shadow: inset 1px 0 shade(@bg_color, 1.1), inset -1px 0 shade(@bg_color, 1.01),
                inset 0 1px shade(@bg_color, 1.1), inset 0 -1px shade(@bg_color, 1.1);
}

window.unity-terminal notebook header {
    background-color: @dark_bg_color;
    background-image: none;
    border: none;
    box-shadow: none;
}
window.unity-terminal notebook header tab {
    padding: 3px 8px;
    border: 1px solid shade(@dark_bg_color, 0.8);
    border-bottom: none;
    border-radius: 3px 3px 0 0;
    background-image: linear-gradient(to bottom, shade(@dark_bg_color, 0.92), shade(@dark_bg_color, 0.9) 60%, shade(@dark_bg_color, 0.85));
    color: mix(@dark_fg_color, @dark_bg_color, 0.2);
    box-shadow: inset 0 1px alpha(shade(@dark_bg_color, 1.26), 0.2);
}
window.unity-terminal notebook header tab:checked {
    background-image: linear-gradient(to bottom, shade(@dark_bg_color, 1.2), shade(@dark_bg_color, 1.12));
    color: @dark_fg_color;
    box-shadow: inset 0 1px shade(@dark_bg_color, 1.26);
}
window.unity-terminal notebook header tab button {
    padding: 0;
    min-width: 16px;
    min-height: 16px;
    color: @dark_fg_color;
    background: none;
    border: none;
    box-shadow: none;
}
window.unity-terminal notebook stack { background-color: #300a24; }
"""


def rgba(value):
    colour = Gdk.RGBA()
    colour.parse(value)
    return colour


def user_shell():
    shell = os.environ.get("SHELL")
    if shell and os.access(shell, os.X_OK):
        return shell
    return pwd.getpwuid(os.getuid()).pw_shell or "/bin/sh"


class Screen(Gtk.Box):
    """One tab: the terminal and its scrollbar."""

    def __init__(self, window, argv, cwd):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.window = window
        self.title_override = None
        self.terminal = Vte.Terminal()
        terminal = self.terminal
        terminal.set_font(Pango.FontDescription.from_string(FONT))
        self.set_zoom(DEFAULT_ZOOM)
        terminal.set_colors(rgba(FOREGROUND), rgba(BACKGROUND), [rgba(c) for c in PALETTE])
        terminal.set_color_cursor(rgba(FOREGROUND))
        terminal.set_color_cursor_foreground(rgba(BACKGROUND))
        terminal.set_cursor_shape(Vte.CursorShape.BLOCK)
        terminal.set_cursor_blink_mode(Vte.CursorBlinkMode.SYSTEM)
        terminal.set_bold_is_bright(True)
        terminal.set_scrollback_lines(10000)
        terminal.set_mouse_autohide(True)
        terminal.set_audible_bell(True)
        terminal.set_allow_hyperlink(True)
        terminal.set_scroll_on_keystroke(True)
        terminal.set_scroll_on_output(False)
        terminal.set_size(80, 24)
        self.link = None
        self.link_tag = terminal.match_add_regex(
            Vte.Regex.new_for_match(r"(https?|ftp|file)://[^\s<>\"'()\[\]]+[^\s<>\"'()\[\].,;:!?]",
                                    -1, PCRE2_MULTILINE), 0)
        terminal.match_set_cursor_name(self.link_tag, "pointer")
        terminal.connect("window-title-changed", lambda *_: window.update_titles())
        terminal.connect("child-exited", self.on_exit)
        terminal.connect("button-press-event", self.on_button)
        terminal.connect("char-size-changed", lambda *_: window.update_geometry())
        scrollbar = Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL, adjustment=terminal.get_vadjustment())
        self.pack_start(terminal, True, True, 0)
        self.pack_start(scrollbar, False, False, 0)
        environment = [f"{k}={v}" for k, v in os.environ.items()
                       if k not in ("COLUMNS", "LINES", "TERM", "COLORTERM", "GTK_THEME", "FONTCONFIG_FILE")]
        environment += ["TERM=xterm-256color", "COLORTERM=truecolor"]
        command = argv or [user_shell()]
        terminal.spawn_async(Vte.PtyFlags.DEFAULT, cwd or os.path.expanduser("~"), command, environment,
                             GLib.SpawnFlags.SEARCH_PATH, None, None, -1, None, self.on_spawned)
        self.show_all()

    def on_spawned(self, terminal, pid, error):
        if error is not None:
            terminal.feed(("\r\n" + error.message + "\r\n").encode())

    def on_exit(self, *_):
        self.window.close_screen(self)

    def title(self):
        return self.title_override or self.terminal.get_window_title() or "Terminal"

    def cwd(self):
        uri = self.terminal.get_current_directory_uri()
        return Gio.File.new_for_uri(uri).get_path() if uri else None

    def set_zoom(self, index):
        self.zoom = max(0, min(len(ZOOMS) - 1, index))
        self.terminal.set_font_scale(ZOOMS[self.zoom])

    def on_button(self, terminal, event):
        if event.button != 3 or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        if terminal.get_has_selection() is False and event.state & Gdk.ModifierType.SHIFT_MASK:
            return False
        self.link = terminal.hyperlink_check_event(event) or terminal.match_check_event(event)[0]
        self.window.popup_context(self, event)
        return True


class TerminalWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Terminal")
        self.get_style_context().add_class(NAME)
        self.set_icon_name("utilities-terminal")
        self.accel = Gtk.AccelGroup()
        self.add_accel_group(self.accel)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.menubar = Gtk.MenuBar()
        box.pack_start(self.menubar, False, False, 0)
        self.notebook = Gtk.Notebook(show_border=False, scrollable=True)
        self.notebook.connect("switch-page", lambda *_: GLib.idle_add(self.on_switch))
        self.notebook.connect("page-added", lambda *_: self.update_tabs())
        self.notebook.connect("page-removed", lambda *_: self.update_tabs())
        box.pack_start(self.notebook, True, True, 0)
        self.add(box)
        self.build_menus()
        box.show_all()

    # ---- menus -------------------------------------------------------------

    def item(self, menu, label, callback=None, accel=None, sensitive=True):
        widget = Gtk.MenuItem.new_with_mnemonic(label)
        if callback:
            widget.connect("activate", lambda *_: callback())
        if accel:
            # GNOME Terminal 3.6 drew no shortcut labels in its menus, so the
            # shortcut belongs to the window rather than the menu item.
            key, mods = Gtk.accelerator_parse(accel)
            self.accel.connect(key, mods, Gtk.AccelFlags.VISIBLE, lambda *_: callback() or True)
        widget.set_sensitive(sensitive and callback is not None)
        menu.append(widget)
        return widget

    def submenu(self, label):
        top = Gtk.MenuItem.new_with_mnemonic(label)
        menu = Gtk.Menu()
        top.set_submenu(menu)
        self.menubar.append(top)
        return top, menu

    def build_menus(self):
        _, menu = self.submenu("_File")
        self.item(menu, "Open _Terminal", self.new_window, "<Shift><Control>n")
        self.item(menu, "Open Ta_b", self.new_tab, "<Shift><Control>t")
        menu.append(Gtk.SeparatorMenuItem())
        self.item(menu, "New _Profile…")
        menu.append(Gtk.SeparatorMenuItem())
        self.close_tab = self.item(menu, "C_lose Tab", lambda: self.close_screen(self.current()), "<Shift><Control>w")
        self.item(menu, "_Close Window", self.destroy, "<Shift><Control>q")

        _, menu = self.submenu("_Edit")
        self.copy_item = self.item(menu, "_Copy", lambda: self.current().terminal.copy_clipboard_format(Vte.Format.TEXT),
                                   "<Shift><Control>c")
        self.paste_item = self.item(menu, "_Paste", lambda: self.current().terminal.paste_clipboard(), "<Shift><Control>v")
        menu.append(Gtk.SeparatorMenuItem())
        self.item(menu, "Select _All", lambda: self.current().terminal.select_all())
        menu.append(Gtk.SeparatorMenuItem())
        self.item(menu, "P_rofiles…")
        self.item(menu, "_Keyboard Shortcuts…")
        self.item(menu, "Pr_ofile Preferences")
        menu.connect("show", lambda *_: self.edit_shown())

        _, menu = self.submenu("_View")
        self.menubar_item = Gtk.CheckMenuItem.new_with_mnemonic("Show _Menubar")
        self.menubar_item.set_active(True)
        self.menubar_item.connect("toggled", lambda item: self.menubar.set_visible(item.get_active()))
        menu.append(self.menubar_item)
        self.fullscreen_item = Gtk.CheckMenuItem.new_with_mnemonic("_Full Screen")
        key, mods = Gtk.accelerator_parse("F11")
        self.accel.connect(key, mods, Gtk.AccelFlags.VISIBLE, lambda *_: self.fullscreen_item.activate() or True)
        self.fullscreen_item.connect("toggled", lambda item: self.fullscreen() if item.get_active() else self.unfullscreen())
        menu.append(self.fullscreen_item)
        menu.append(Gtk.SeparatorMenuItem())
        self.item(menu, "Zoom _In", lambda: self.zoom(1), "<Control>plus")
        self.item(menu, "_Normal Size", lambda: self.zoom(0), "<Control>0")
        self.item(menu, "Zoom _Out", lambda: self.zoom(-1), "<Control>minus")

        _, menu = self.submenu("_Search")
        self.item(menu, "_Find…", self.find, "<Shift><Control>f")
        self.item(menu, "Find Ne_xt", lambda: self.current().terminal.search_find_next(), "<Shift><Control>g")
        self.item(menu, "Find Pre_vious", lambda: self.current().terminal.search_find_previous(), "<Shift><Control>h")
        self.item(menu, "_Clear Highlight", lambda: self.current().terminal.search_set_regex(None, 0), "<Shift><Control>j")

        _, menu = self.submenu("_Terminal")
        profile = Gtk.MenuItem.new_with_mnemonic("Change _Profile")
        profiles = Gtk.Menu()
        default = Gtk.RadioMenuItem.new_with_label(None, "Default")
        default.set_active(True)
        profiles.append(default)
        profile.set_submenu(profiles)
        menu.append(profile)
        self.item(menu, "_Set Title…", self.set_title_dialog)
        encoding = Gtk.MenuItem.new_with_mnemonic("Set _Character Encoding")
        encodings = Gtk.Menu()
        utf8 = Gtk.RadioMenuItem.new_with_label(None, "Current Locale (UTF-8)")
        utf8.set_active(True)
        encodings.append(utf8)
        encoding.set_submenu(encodings)
        menu.append(encoding)
        menu.append(Gtk.SeparatorMenuItem())
        self.item(menu, "_Reset", lambda: self.current().terminal.reset(True, False))
        self.item(menu, "Reset and C_lear", lambda: self.current().terminal.reset(True, True))

        # GNOME Terminal shows its Tabs menu only while a window has tabs.
        self.tabs_top, menu = self.submenu("Ta_bs")
        self.item(menu, "_Previous Tab", lambda: self.notebook.prev_page(), "<Control>Page_Up")
        self.item(menu, "_Next Tab", lambda: self.notebook.next_page(), "<Control>Page_Down")
        self.item(menu, "Move Tab _Left", lambda: self.move_tab(-1), "<Shift><Control>Page_Up")
        self.item(menu, "Move Tab _Right", lambda: self.move_tab(1), "<Shift><Control>Page_Down")

        _, menu = self.submenu("_Help")
        self.item(menu, "_Contents", None, "F1")
        self.item(menu, "_About", self.about)

    def edit_shown(self):
        self.copy_item.set_sensitive(self.current().terminal.get_has_selection())
        self.paste_item.set_sensitive(Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_is_text_available())

    def popup_context(self, screen, event):
        menu = Gtk.Menu()
        menu.attach_to_widget(screen.terminal, None)
        if screen.link:
            link = screen.link
            self.item(menu, "_Open Link", lambda: Gtk.show_uri_on_window(self, link, Gdk.CURRENT_TIME))
            self.item(menu, "_Copy Link Address",
                      lambda: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(link, -1))
            menu.append(Gtk.SeparatorMenuItem())
        copy = self.item(menu, "_Copy", lambda: screen.terminal.copy_clipboard_format(Vte.Format.TEXT))
        copy.set_sensitive(screen.terminal.get_has_selection())
        self.item(menu, "_Paste", lambda: screen.terminal.paste_clipboard())
        menu.append(Gtk.SeparatorMenuItem())
        show = Gtk.CheckMenuItem.new_with_mnemonic("Show _Menubar")
        show.set_active(self.menubar.get_visible())
        show.connect("toggled", lambda item: self.menubar_item.set_active(item.get_active()))
        menu.append(show)
        menu.show_all()
        menu.popup_at_pointer(event)

    # ---- tabs --------------------------------------------------------------

    def current(self):
        return self.notebook.get_nth_page(self.notebook.get_current_page())

    def add_screen(self, argv=None, cwd=None):
        screen = Screen(self, argv, cwd)
        label = Gtk.Box(spacing=4)
        text = Gtk.Label(label="Terminal", ellipsize=Pango.EllipsizeMode.END, width_chars=12)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_focus_on_click(False)
        close.connect("clicked", lambda *_: self.close_screen(screen))
        label.pack_start(text, True, True, 0)
        label.pack_start(close, False, False, 0)
        label.show_all()
        screen.label = text
        page = self.notebook.append_page(screen, label)
        self.notebook.set_tab_reorderable(screen, True)
        self.notebook.set_current_page(page)
        screen.terminal.grab_focus()
        self.update_geometry()
        return screen

    def close_screen(self, screen):
        if screen is None or self.notebook.page_num(screen) < 0:
            return
        self.notebook.remove_page(self.notebook.page_num(screen))
        if self.notebook.get_n_pages() == 0:
            self.destroy()

    def move_tab(self, step):
        screen = self.current()
        count = self.notebook.get_n_pages()
        self.notebook.reorder_child(screen, (self.notebook.page_num(screen) + step) % count)

    def update_tabs(self):
        many = self.notebook.get_n_pages() > 1
        self.notebook.set_show_tabs(many)
        self.tabs_top.set_visible(many)
        self.close_tab.set_sensitive(many)
        self.update_titles()

    def on_switch(self):
        screen = self.current()
        if screen:
            screen.terminal.grab_focus()
            self.update_titles()
        return False

    def update_titles(self):
        for index in range(self.notebook.get_n_pages()):
            screen = self.notebook.get_nth_page(index)
            screen.label.set_text(screen.title())
        screen = self.current()
        if screen:
            self.set_title(screen.title())

    def update_geometry(self):
        screen = self.current()
        if screen is None:
            return
        terminal = screen.terminal
        geometry = Gdk.Geometry()
        geometry.width_inc = terminal.get_char_width()
        geometry.height_inc = terminal.get_char_height()
        geometry.min_width = geometry.width_inc * 2
        geometry.min_height = geometry.height_inc * 2
        self.set_geometry_hints(terminal, geometry,
                                Gdk.WindowHints.RESIZE_INC | Gdk.WindowHints.MIN_SIZE)

    # ---- actions -----------------------------------------------------------

    def new_window(self):
        window = TerminalWindow(self.get_application())
        window.add_screen(cwd=self.current().cwd())
        window.present()

    def new_tab(self):
        self.add_screen(cwd=self.current().cwd())

    def zoom(self, step):
        screen = self.current()
        screen.set_zoom(DEFAULT_ZOOM if step == 0 else screen.zoom + step)

    def set_title_dialog(self):
        screen = self.current()
        dialog = Gtk.Dialog(title="Set Title", transient_for=self, modal=True)
        dialog.add_buttons("_Cancel", Gtk.ResponseType.CANCEL, "_OK", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        row = Gtk.Box(spacing=12, border_width=12)
        row.pack_start(Gtk.Label.new_with_mnemonic("_Title:"), False, False, 0)
        entry = Gtk.Entry(text=screen.title(), activates_default=True)
        row.pack_start(entry, True, True, 0)
        dialog.get_content_area().add(row)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            screen.title_override = entry.get_text() or None
            self.update_titles()
        dialog.destroy()

    def find(self):
        terminal = self.current().terminal
        dialog = Gtk.Dialog(title="Find", transient_for=self)
        dialog.add_buttons("_Close", Gtk.ResponseType.CLOSE, "_Find", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        grid = Gtk.Grid(row_spacing=6, column_spacing=12, border_width=12)
        grid.attach(Gtk.Label.new_with_mnemonic("_Search for:"), 0, 0, 1, 1)
        entry = Gtk.Entry(activates_default=True, hexpand=True)
        grid.attach(entry, 1, 0, 1, 1)
        options = {}
        for row, (key, label) in enumerate([("case", "_Match case"), ("word", "Match _entire word only"),
                                            ("regex", "Match as _regular expression"),
                                            ("back", "Search _backwards"), ("wrap", "_Wrap around")], 1):
            check = Gtk.CheckButton.new_with_mnemonic(label)
            check.set_active(key == "wrap")
            grid.attach(check, 0, row, 2, 1)
            options[key] = check
        dialog.get_content_area().add(grid)
        dialog.show_all()

        def respond(_dialog, response):
            if response != Gtk.ResponseType.OK:
                dialog.destroy()
                return
            text = entry.get_text()
            if not text:
                return
            pattern = text if options["regex"].get_active() else re.escape(text)
            if options["word"].get_active():
                pattern = r"\b" + pattern + r"\b"
            flags = PCRE2_MULTILINE | (0 if options["case"].get_active() else PCRE2_CASELESS)
            try:
                terminal.search_set_regex(Vte.Regex.new_for_search(pattern, -1, flags), 0)
            except GLib.Error:
                return
            terminal.search_set_wrap_around(options["wrap"].get_active())
            if options["back"].get_active():
                terminal.search_find_previous()
            else:
                terminal.search_find_next()

        dialog.connect("response", respond)

    def about(self):
        dialog = Gtk.AboutDialog(transient_for=self, modal=True, program_name="Terminal",
                                 logo_icon_name="utilities-terminal",
                                 comments="Unity 12.10's terminal on the current VTE "
                                          + "%d.%d" % (Vte.get_major_version(), Vte.get_minor_version()))
        dialog.run()
        dialog.destroy()


class Application(Gtk.Application):
    def __init__(self, argv):
        super().__init__(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.argv = argv

    def do_activate(self):
        settings = Gtk.Settings.get_default()
        settings.set_property("gtk-font-name", "Ubuntu 11")
        settings.set_property("gtk-application-prefer-dark-theme", True)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        window = TerminalWindow(self)
        window.add_screen(self.argv, os.getcwd())
        window.present()


def main():
    argv = sys.argv[1:]
    # x-terminal-emulator and gnome-terminal style command options.
    if argv[:1] in (["-e"], ["-x"], ["--"]):
        argv = argv[1:]
    if len(argv) == 1 and " " in argv[0] and not os.path.exists(argv[0]):
        argv = ["/bin/sh", "-c", argv[0]]
    GLib.set_prgname(NAME)
    Gdk.set_program_class(NAME)
    sys.exit(Application(argv).run([sys.argv[0]]))


if __name__ == "__main__":
    main()
