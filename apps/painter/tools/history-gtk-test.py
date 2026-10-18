# -*- coding: utf-8 -*-
"""Bounded scrolling fixture; only imported inside the private GTK harness."""
from __future__ import unicode_literals
import os
assert os.environ['HOME'] == '/home/test' and os.environ['DISPLAY'] == ':93'
from gi.repository import Gtk, GdkPixbuf
from unity_frontend import Window
from unity_widgets import HistoryGrid


def run():
    class History(object):
        history_scrolled = Window.history_scrolled.im_func
        request_visible_history = Window.request_visible_history.im_func
        history_settled = Window.history_settled.im_func
        update_gallery = Window.update_gallery.im_func
        def selected(self):
            self.selection = self.tiles[self.gallery.get_selected_items()[0]][2]
        def send(self, op):
            assert op == 'poll'
            self.requests += 1
            self.state = dict(gallery=self.rows[self.offset:self.offset + self.history_limit],
                              offset=self.offset, total=len(self.rows), replacement='')
            self.update_gallery(self.state)
    h = History()
    h.offset, h.history_limit, h.requests = 0, 60, 0
    h.history_pending, h.rebuilding_gallery, h.grabbed_live = False, False, False
    h.history_anchor = h.gallery_key = h.walk_pending = None
    h.history_fetch_timer = h.history_demand = None
    h.selection = ''
    h.rows = [dict(path='/fake/%d.png' % n, name='%d.png' % n, thumb='', poster='',
                   is_video=False, live=False, grab=False) for n in range(5000)]
    h.tiles = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, GdkPixbuf.Pixbuf)
    h.gallery = HistoryGrid(h.tiles)
    h.history_scroll = Gtk.ScrolledWindow()
    h.history_scroll.add(h.gallery)
    h.history_scroll.get_vadjustment().connect('value-changed', h.history_scrolled)
    h.tally = Gtk.Label()
    fixture = Gtk.OffscreenWindow()
    fixture.set_default_size(640, 400)
    fixture.add(h.history_scroll)
    fixture.show_all()
    h.send('poll')
    def settle():
        while Gtk.events_pending(): Gtk.main_iteration()
        h.history_settled()
        while Gtk.events_pending(): Gtk.main_iteration()
    settle()
    initial = h.selection
    adj = h.history_scroll.get_vadjustment()
    for _ in range(100):
        if h.offset + len(h.tiles) == len(h.rows): break
        before = h.offset + len(h.tiles)
        adj.set_value(adj.get_upper() - adj.get_page_size())
        settle()
        assert h.offset + len(h.tiles) > before, (before, h.offset, len(h.tiles))
        assert len(h.tiles) <= 180
        assert h.selection == initial, 'scrolling changed the preview selection'
    assert h.offset + len(h.tiles) == len(h.rows)
    for _ in range(100):
        if h.offset == 0: break
        before = h.offset
        adj.set_value(0)
        settle()
        assert h.offset < before, (before, h.offset)
    assert h.offset == 0
    assert len(h.gallery.thumb_cache) <= 64 and h.gallery.thumb_jobs.qsize() <= 64
    requests = h.requests
    for _ in range(10): h.update_gallery(h.state)
    settle()
    assert requests == h.requests, 'unchanged poll causes a paging loop'
    fixture.destroy()
    print('PASS: 5000-row history scrolls both ways with bounded rows and stable selection')
