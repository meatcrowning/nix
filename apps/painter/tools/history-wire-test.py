# -*- coding: utf-8 -*-
"""Actual async gallery/socket/decoder regression, in unity-test.sh only."""
from __future__ import unicode_literals
import os, sys, time, traceback
assert os.environ['HOME'] == '/home/test' and os.environ['DISPLAY'] == ':93'
sys.path.insert(0, '/home/test/nix/apps/painter')
from unity_frontend import Window, Gtk, GLib, GObject
GObject.threads_init()
w = Window(sys.argv[1])
started = time.time()
progress = [0]
failed = [False]
def check():
    try:
        assert time.time() - started < 45, ('history stalled', progress, w.offset, w.history_limit, w.state.get('offset'), len(w.tiles), w.history_pending)
        if not w.tiles: return True
        visible = w.gallery.get_visible_range()
        if not visible or visible[0] is None: return True
        first, last = [p.get_indices()[0] for p in visible]
        ready = all(w.tiles[n][0] is not None for n in range(first, last + 1))
        if not ready: return True
        if progress[0] == 0:
            cell = w.gallery.pixbuf_cell
            assert cell.get_property('height') < w.gallery.cell_width * .7, 'landscape thumbnails reserve square-height slots'
        progress[0] += 1
        if w.offset + last >= 295:
            print('PASS: actual thumbnails load across controller-backed history windows', w.offset, last)
            w.connection.close()
            Gtk.main_quit()
            return False
        adj = w.history_scroll.get_vadjustment()
        adj.set_value(min(adj.get_upper()-adj.get_page_size(), adj.get_value()+adj.get_page_size()*.8))
        return True
    except Exception:
        traceback.print_exc()
        failed[0] = True
        w.connection.close()
        Gtk.main_quit()
        return False
GLib.timeout_add(80, check)
Gtk.main()
sys.exit(1 if failed[0] else 0)
