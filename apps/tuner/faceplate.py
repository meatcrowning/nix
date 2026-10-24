"""One illuminated receiver face; the rest of the window keeps its GTK theme."""

from gi.repository import Gtk


CSS = b"""
#tuner-face {
    background-image: linear-gradient(to bottom, #1e1b15, #0d0b07 45%, #141009);
    color: #ff9929;
    border: 2px solid #35312a;
    border-radius: 7px;
    box-shadow: inset 0 1px 2px #000000;
    padding: 7px;
}
#tuner-face * {
    font-family: "Ubuntu Mono";
    color: #ff9929;
    text-shadow: none;
    -gtk-icon-shadow: none;
}
#tuner-face menu { background: #151109; border: 1px solid #68451f; }
#tuner-face menuitem:hover { background: #49321a; }
#tuner-face toolbar { background: transparent; border: none; box-shadow: none; }
#tuner-face button, #tuner-face entry {
    background-image: none;
    background-color: #151109;
    border: 1px solid #68451f;
    border-radius: 3px;
    box-shadow: inset 0 1px alpha(#ffbb62, 0.08);
    padding: 5px 9px;
}
#tuner-face button:hover { background-color: #30200e; border-color: #ff9929; }
#tuner-face button:checked, #tuner-face button:active {
    background-color: #ff9929;
    color: #171008;
    box-shadow: none;
}
#tuner-face button:checked *, #tuner-face button:active * { color: #171008; }
#tuner-face *:disabled { color: #80613b; }
#tuner-face button:disabled { border-color: #393024; background-color: #151109; }
#tuner-face entry:focus { border-color: #ffbb62; }
#tuner-face entry selection { background-color: #ff9929; color: #171008; }
#tuner-face separator { background-color: #49321a; min-width: 1px; }
#tuner-face scale trough, #tuner-face levelbar trough {
    background: #080704;
    border: 1px solid #49321a;
    border-radius: 1px;
    box-shadow: none;
}
#tuner-face scale highlight, #tuner-face levelbar block.filled {
    background: #ff9929;
    border-color: #ffb34f;
    border-radius: 0;
}
#tuner-face levelbar block.empty { background: #292015; border-color: #292015; }
#tuner-face scale slider {
    background: #ffbb62;
    border: 1px solid #ff9929;
    border-radius: 2px;
    box-shadow: none;
    min-width: 9px;
    min-height: 17px;
}
"""


def style_faceplate(widget):
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        widget.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
