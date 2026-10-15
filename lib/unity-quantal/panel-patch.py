"""Small integration points in the unmodified Unity 6.8 panel service."""
from pathlib import Path

path = Path('services/panel-service.c')
source = path.read_text()

def replace(old, new):
    global source
    assert source.count(old) == 1, old
    source = source.replace(old, new)

replace('#include "panel-service.h"', '#include "panel-service.h"\n#include "now-playing.h"\n#include "user-menu.h"')
replace('  {"libsoundmenu.so", NULL},', '  {"libnowplaying.so", NULL},\n  {"libsoundmenu.so", NULL},')
replace('  {"libsession.so", NULL},', '  {"libusermenu.so", NULL},\n  {"libsession.so", NULL},')
replace('static void\nload_indicators (PanelService *self)', '''static gboolean
now_playing_hovered (gpointer panel, IndicatorObject *indicator)
{
  gint x, y;
  GdkDeviceManager *manager = gdk_display_get_device_manager (gdk_display_get_default ());
  gdk_device_get_position (gdk_device_manager_get_client_pointer (manager), NULL, &x, &y);
  IndicatorObjectEntry *entry = get_entry_at (PANEL_SERVICE (panel), x, y);
  return entry && get_entry_parent_indicator (entry) == indicator;
}

static void
load_indicators (PanelService *self)''')
replace('  g_dir_close (dir);', '''  g_dir_close (dir);
  load_indicator (self, now_playing_new (now_playing_hovered, self), "libnowplaying.so");
  load_indicator (self, user_menu_new (), "libusermenu.so");''')
path.write_text(source)
