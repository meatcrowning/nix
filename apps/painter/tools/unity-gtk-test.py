#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Real Quantal GTK controls, only inside unity-test.sh's private X server."""
from __future__ import unicode_literals
import os
import sys
import traceback
assert os.environ['HOME'] == '/home/test'
assert os.environ['DISPLAY'] == ':93'
sys.path.insert(0, '/home/test/nix/apps/painter')
from unity_frontend import Gtk, GLib, GObject, Window
from gi.repository import Gdk
GObject.threads_init()
assert (Gtk.get_major_version(), Gtk.get_minor_version()) == (3, 6)
assert Gtk.Settings.get_default().get_property('gtk-theme-name') in ('Ambiance', 'Ambiance-Dark')

# A private global-menu registrar proves GTK exports real menu actions. There
# is no Unity shell, focus change, notification daemon, or session manager.
registrations = []
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
owner = dbus.service.BusName('com.canonical.AppMenu.Registrar', bus)
class Registrar(dbus.service.Object):
    @dbus.service.method('com.canonical.AppMenu.Registrar', in_signature='uo', out_signature='', sender_keyword='sender')
    def RegisterWindow(self, xid, path, sender=None):
        registrations.append((int(xid), sender, str(path)))
    @dbus.service.method('com.canonical.AppMenu.Registrar', in_signature='u', out_signature='')
    def UnregisterWindow(self, xid):
        pass
    @dbus.service.method('com.canonical.AppMenu.Registrar', in_signature='', out_signature='a(uso)')
    def GetMenus(self):
        return registrations
registrar = Registrar(bus, '/com/canonical/AppMenu/Registrar')
notifications = []
notification_hints = []
notification_owner = dbus.service.BusName('org.freedesktop.Notifications', bus)
class Notifications(dbus.service.Object):
    @dbus.service.method('org.freedesktop.Notifications', in_signature='susssasa{sv}i', out_signature='u')
    def Notify(self, app, replaces, icon, summary, body, actions, hints, timeout):
        notifications.append(str(body))
        notification_hints.append(dict(hints))
        assert list(actions) == ["default", "Open Painter"], actions
        return 1
notification_server = Notifications(bus, '/org/freedesktop/Notifications')
window = Window(sys.argv[1])
window.message('Generation completed')
step = [0]
failed = [False]
video_tick = ['']
zoom_point = [None]

def select(name):
    for i, row in enumerate(window.tiles):
        if row[2].endswith('/' + name):
            window.gallery.select_path(Gtk.TreePath.new_from_string(str(i)))
            return
    raise AssertionError('missing output: ' + name)

def copied_pixels(width, height):
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    # Quantal's GI bindings mis-marshal the atom array from wait_for_targets.
    available = lambda target: clipboard.wait_is_target_available(Gdk.Atom.intern(target, False))
    assert available('image/png')
    for target in ('text/plain', 'text/plain;charset=utf-8', 'text/html',
                   'text/uri-list', 'UTF8_STRING', 'STRING', 'TEXT',
                   'x-special/gnome-copied-files'):
        assert not available(target), target
    data = clipboard.wait_for_contents(Gdk.Atom.intern('image/png', False)).get_data()
    assert data.startswith(b'\x89PNG\r\n\x1a\n')
    pixbuf = clipboard.wait_for_image()
    assert (pixbuf.get_width(), pixbuf.get_height()) == (width, height)

def test():
    try:
        if not window.state.get('model'):
            return True
        if step[0] == 0:
            from moss_gtk import TokenMarks
            token_view, count = Gtk.TextView(), Gtk.Label()
            sent = []
            marks = TokenMarks(token_view, count, lambda *a, **kw: sent.append((a, kw)))
            token_state = dict(flags=dict(layoutSupport=True), ready=True)
            marks.update(token_state)
            token_view.get_buffer().set_text('red cube')
            assert marks.timer and not marks.boundaries
            marks.destroy()  # drive the debounce deadline explicitly
            marks.submit()
            assert sent[-1][1]['text'] == 'red cube'
            token_state['tokenResults'] = {marks.identity: dict(text='red cube', result=dict(count=12, template_tokens=10, boundaries=[3]))}
            marks.update(token_state)
            assert count.get_text() == '2 tok' and marks.boundaries == [3]
            buf = token_view.get_buffer()
            assert buf.get_iter_at_offset(1).has_tag(marks.tags[0])
            assert buf.get_iter_at_offset(4).has_tag(marks.tags[1])
            assert marks.tags[0].get_property('background-gdk') != marks.tags[1].get_property('background-gdk')
            class PickView(object):
                def window_to_buffer_coords(self, *args): return (0, 0)
                def get_iter_at_location(self, *args): return buf.get_iter_at_offset(4)
            class PickEvent(object):
                button, x, y = 1, 0, 0
            marks.picking = True
            assert marks.pick(PickView(), PickEvent())
            assert sent[-1] == (('heatmap_pick',), dict(text='red cube', position=4, region=''))
            marks.picking = False
            assert not marks.pick(PickView(), PickEvent())
            token_view.get_buffer().set_text('red sphere')
            marks.update(token_state)
            assert not marks.boundaries
            assert not token_view.get_buffer().get_iter_at_offset(1).has_tag(marks.tags[0])
            assert marks.text() == 'red sphere'
            token_view.destroy()
            print('PASS: GTK token debounce, count, markers and stale result rejection')
            send = window.send
            heatmap_state = window.state.get('heatmap')
            requests = []
            window.send = lambda op, **kw: requests.append((op, kw))
            window.state['heatmap'] = dict(available=True, path=window.selection, selected=-1,
                tokens=[dict(label='1 · red'), dict(label='2 · cube')], overlay='')
            window.toggle_heatmap()
            assert window.heatmap_picker.get_visible() and window.history_scroll.get_visible()
            assert isinstance(window.heatmap_picker.get_parent(), Gtk.Toolbar)
            assert window.heatmap_tokens.get_active() == 0
            assert window.heatmap_grid.get_visible()
            window.heatmap_grid.emit('clicked')
            assert requests[-1][0] == 'heatmap_grid'
            window.receive('heatmap_grid', dict(ok=True, state=dict(heatmap=dict(
                window.state['heatmap'], picking=True, gridLabel=u'Pick token 1/2 · Cancel'))))
            assert all(m.picking for m in window.token_marks)
            grid_label = window.heatmap_grid.get_label()
            if isinstance(grid_label, bytes): grid_label = grid_label.decode('utf-8')
            assert grid_label == u'Pick token 1/2 · Cancel'
            window.heatmap_tokens.set_active(1)
            assert requests[-1][0] == 'heatmap_select' and requests[-1][1]['index'] == 0
            window.toggle_heatmap()
            assert not window.heatmap_picker.get_visible() and not window.heatmap_grid.get_visible()
            window.send = send
            if heatmap_state is None: window.state.pop('heatmap', None)
            else: window.state['heatmap'] = heatmap_state
            print('PASS: GTK heatmap toolbar selector and accessible history')
            from unity_widgets import ImageView
            from gi.repository import GdkPixbuf
            mask_view = ImageView(lambda *args: None, lambda: None)
            source_pixels = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 4, 4)
            source_pixels.fill(0x0000ffff)
            mask_view.frame(source_pixels)
            before_pixels = bytes(mask_view.picture.get_pixbuf().get_pixels())
            mask = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 2, 2)
            mask.fill(0xffdc00cc)
            mask_view.set_heatmap(mask)
            assert mask_view.original is source_pixels
            assert bytearray(mask_view.picture.get_pixbuf().get_pixels())[0] > 100
            mask_view.set_heatmap(None)
            assert bytes(mask_view.picture.get_pixbuf().get_pixels()) == before_pixels
            mask_view.destroy()
            print('PASS: GTK heatmap composition keeps decoded source and restores it without reload')
            assert notifications == ['Generation completed'], notifications
            buttons = window.wildcard_buttons.get_children()
            assert [b.get_label() for b in buttons] == window.state['wildcards']
            card = window.wildcard_cards['pose']
            card.show()
            while Gtk.events_pending(): Gtk.main_iteration()
            assert card.window.get_mapped() and len(card.checks) == len(window.state['wildcardOptions']['pose'])
            class Crossing:
                detail = Gdk.NotifyType.NONLINEAR
            card.cross(card.button, Crossing(), False, False)
            card.cross(card.window, Crossing(), True, True)
            card.maybe_hide()
            assert card.window.get_visible()
            card.checks[0].set_active(False)
            card.hide()

            buffer = window.controls['positive'].get_buffer()
            buffer.set_text('alpha omega')
            buffer.place_cursor(buffer.get_iter_at_offset(6))
            next(b for b in buttons if b.get_label() == 'pose').clicked()
            assert window.values()['positive'] == 'alpha __pose__omega'
            buffer.select_range(buffer.get_iter_at_offset(6), buffer.get_iter_at_offset(14))
            next(b for b in buttons if b.get_label() == 'gaze').clicked()
            assert window.values()['positive'] == 'alpha __gaze__omega'
            window.original_active = window.is_active
            window.is_active = lambda: True
            window.message('Focused completion', completion=True)
            window.is_active = lambda: False
            window.message('Focus returned before dispatch', completion=True)
            window.is_active = lambda: True
            assert not window.info.get_visible()
            assert len(window.state['models']) == 2
            assert window.selectors.get_orientation() == Gtk.Orientation.HORIZONTAL
            assert window.selector_columns[0].get_allocation().y == window.selector_columns[1].get_allocation().y
            narrow = Gdk.Rectangle()
            narrow.width = 300
            window.arrange_selectors(window.selectors, narrow)
            assert window.selectors.get_orientation() == Gtk.Orientation.VERTICAL
            window.arrange_selectors(window.selectors, window.selectors.get_allocation())
            selected_model = next(m for m in window.state['models'] if m['name'] == window.state['model'])
            assert window.model_info.get_text() == (selected_model.get('problem') or '')
            assert window.model_info.get_visible() == bool(selected_model.get('problem'))
            window.sidebar_split.set_position(440)
            window.sidebar_split.emit('accept-position')
            assert window.browse_pane.get_orientation() == Gtk.Orientation.HORIZONTAL
            window.browse_pane.set_position(360)
            window.browse_pane.emit('button-release-event', Gdk.Event.new(Gdk.EventType.BUTTON_RELEASE))
            assert window.history_tally in window.status.get_text().decode('utf-8')
            assert window.sampling.get_expanded()
            window.sampling.set_expanded(False)
            assert not window.sampling.get_expanded()
            assert window.controls['steps'].get_parent() == window.sampling.get_child().get_children()[0]
            assert window.get_title() == 'Painter'
            assert window.actions['generate'][0].get_sensitive()
            # Plain text-to-image families such as MOSS expose no advanced UI.
            flags = window.state['flags']
            window.state['flags'] = dict(isEdit=False, isVideo=False, supportsPatches=False,
                                        supportsLoras=False, encoderControls=False,
                                        referenceImages=False, optionalEditImage=False)
            window.visibility()
            assert not window.advanced.get_visible()
            assert not window.input_button.get_visible()
            for key in ('positive', 'negative', 'steps', 'cfg', 'sampler_name',
                        'scheduler', 'denoise', 'megapixels', 'aspectW'):
                rows = window.rows[key]
                assert all(w.get_visible() for w in (rows if isinstance(rows, tuple) else (rows,))), key
            for key in ('slg_single_layers', 'slg_start_percent', 'slg_end_percent'):
                assert not window.controls[key].get_visible()
            window.state['flags']['layoutSupport'] = True
            window.visibility()
            for key in ('slg_single_layers', 'slg_start_percent', 'slg_end_percent'):
                assert window.controls[key].get_visible()
            window.loading = True
            window.controls['slg_single_layers'].set_text('24, 26')
            window.controls['slg_start_percent'].set_value(.125)
            window.controls['slg_end_percent'].set_value(.875)
            values = window.values()
            assert values['slg_single_layers'] == '24, 26'
            assert values['slg_start_percent'] == .125 and values['slg_end_percent'] == .875
            window.apply_settings(dict(slg_single_layers='22', slg_start_percent=0, slg_end_percent=1))
            window.loading = False
            window.state['flags'] = flags
            window.visibility()
            shot = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0, window.get_allocated_width(), window.get_allocated_height())
            shot.savev('/home/test/window.png', 'png', [], [])
            assert window.text_boxes['positive'].height == 210
            # Exercise the handle's press/motion/release contract using local
            # events only, inside this private X server.
            class Event:
                button = 1
                y_root = 100
            for key, delta, expected in [('positive', 75, 285), ('negative', -1000, 40),
                                         ('system_prompt', 1000, 600)]:
                box = window.text_boxes[key]
                event = Event()
                box.press(box.handle, event)
                event.y_root += delta
                box.motion(box.handle, event)
                box.release(box.handle, event)
                assert box.height == expected
            window.controls['aspectW'].set_value(16)
            window.controls['aspectH'].set_value(9)
            window.controls['megapixels'].set_value(.8)
            window.controls['positive'].get_buffer().set_text('a native GTK prompt')
            window.controls['count'].set_value(2)
            window.randomize_seed()
            assert window.values()['randomSeed']
            window.new_fixed_seed()
            assert not window.values()['randomSeed'] and 0 <= window.values()['seed'] < 2**53
            window.controls['seedPolicy'].set_active_id('Reuse last')
            assert window.values()['reuseSeed'] and not window.values()['randomSeed']
            window.controls['seedPolicy'].set_active_id('Fixed')
            window.controls['seed'].set_text('1234')
            window.generate()
        elif step[0] == 1:
            assert not window.state['wildcardOptions']['pose'][0]['enabled']
            window.send('wildcard_line', name='pose', index=0, enabled=True)
            assert notifications == ['Generation completed'], notifications
            window.is_active = lambda: False
            window.message('Background completion', completion=True)
            assert window.state['settings']['positive'] == 'a native GTK prompt'
            assert window.state['settings']['aspectW'] == 16
            assert window.state['settings']['aspectH'] == 9
            assert window.state['settings']['megapixels'] == .8
            assert len(window.tiles) == 3
            from unity_widgets import HistoryGrid
            from gi.repository import GdkPixbuf
            model = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, GdkPixbuf.Pixbuf)
            original = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 140, 100)
            original.fill(0xff0000ff)
            for n in range(12): model.append([original, 'a long generated output filename %d.png' % n, str(n), original])
            fixture = Gtk.OffscreenWindow()
            fixture.set_default_size(640, 400)
            grid = HistoryGrid(model)
            viewport = Gtk.ScrolledWindow()
            viewport.add(grid)
            fixture.add(viewport)
            fixture.show_all()
            for width in (640, 800, 480, 400):
                fixture.resize(width, 400)
                while Gtk.events_pending(): Gtk.main_iteration()
                available = grid.get_allocated_width() - 2 * grid.get_margin()
                columns = max(1, (available + grid.get_column_spacing()) // (112 + 2 * (grid.get_item_padding() + grid.focus_width()) + grid.get_column_spacing()))
                assert grid.get_item_row(Gtk.TreePath.new_from_string(str(columns - 1))) == 0, ('history row wastes a column', width, columns, grid.get_item_width())
                assert grid.get_item_row(Gtk.TreePath.new_from_string(str(columns))) == 1
            fixture.destroy()
            from importlib import import_module
            import_module("history-gtk-test").run()
            select('fixture.png')
            window.view()
            assert window.pages.get_current_page() == 1
            window.restore()
        elif step[0] == 2:
            assert notifications == ['Generation completed', 'Background completion'], notifications
            assert notification_hints[-1].get('transient') == True
            assert not notification_hints[0].get('transient', False)
            window.is_active = window.original_active
            assert window.values()['positive'] == 'restored prompt'
            assert window.values()['seed'] == 42
            assert window.values()['aspectW'] == 4
            assert window.values()['aspectH'] == 5
            from dimensions import calc_dims
            assert calc_dims('4:5', window.values()['megapixels'], window.state['multiple']) == (640, 768)
            assert registrations, 'GTK global menu did not register'
            assert window.picture.get_pixbuf() is not None
            assert window.viewer.scale > 1.0, ('fit size', window.viewer.scale, window.viewer.scroll.get_allocated_width(), window.viewer.scroll.get_allocated_height())
            scale = window.viewer.scale
            window.zoom_by(1.25)
            while Gtk.events_pending(): Gtk.main_iteration()
            assert abs(window.viewer.scale - scale * 1.25) < .001
            window.fit_image()
            assert window.viewer.zoom == 0
            # The preview menu copies the original, even when displayed enlarged.
            class RightClick:
                button = 3
                time = 0
            assert window.preview_menu(window.viewer.events, RightClick())
            item = window.image_menu.get_children()[0]
            assert item.get_label() == 'Copy Image'
            window.image_menu.popdown()
            item.activate()
            window.viewer.set_zoom(1)
            while Gtk.events_pending(): Gtk.main_iteration()
            assert window.picture.get_pixbuf().get_width() == 80
            window.browse()
            assert window.viewer.get_parent() == window.preview_box
            assert window.picture.get_pixbuf() is not None
            select('edit.png')
        elif step[0] == 3:
            copied_pixels(80, 60)
            # Copy another thumbnail without changing the selected preview.
            path = next(r['path'] for r in window.state['gallery'] if r['name'] == 'fixture.png')
            menu = window.make_image_menu(path)
            assert menu is not None
            menu.get_children()[0].activate()
            assert window.selection.endswith('/edit.png')
            assert window.make_image_menu('live://generating') is None
            assert window.make_image_menu('/missing.png') is None
            clip = next(r['path'] for r in window.state['gallery'] if r['name'] == 'clip.mp4')
            assert window.make_image_menu(clip) is None
            assert window.viewer.before is not None
            window.viewer.compare.set_value(0)
            red = window.picture.get_pixbuf().get_pixels()
            window.viewer.compare.set_value(100)
            blue = window.picture.get_pixbuf().get_pixels()
            assert red != blue, 'comparison slider did not reveal before image'
            select('clip.mp4')
        elif step[0] == 4:
            copied_pixels(80, 60)
            assert notifications == ['Generation completed', 'Background completion'], notifications
            assert notification_hints[-1].get('transient') == True
            assert not notification_hints[0].get('transient', False)
            assert window.viewer.video
            assert window.picture.get_pixbuf() is not None
            assert window.viewer.natural_size == [96, 64]
            assert window.viewer.duration > 0
            video_tick[0] = window.frame_tick
            window.viewer.set_zoom(2)
            assert window.viewer.zoom == 0, 'video zoom must be disabled'
            window.view()
        elif step[0] == 5:
            assert video_tick[0] != window.frame_tick, 'clip frames did not advance/loop'
            window.send('playback')
        elif step[0] == 6:
            video_tick[0] = window.frame_tick
        elif step[0] == 7:
            assert video_tick[0] == window.frame_tick, 'paused clip still advancing'
            select('fixture.png')
        elif step[0] == 8:
            assert not window.viewer.video
            assert window.viewer.original.get_width() == 80
            window.view()
            window.viewer.set_zoom(16)
        elif step[0] in (9, 11):
            view = window.viewer
            if step[0] == 9:
                view.scroll.get_hadjustment().set_value(120)
                view.scroll.get_vadjustment().set_value(90)
            cx, cy = 210.0, 145.0
            zoom_point[0] = ((cx + view.scroll.get_hadjustment().get_value() - view.image_origin[0]) / view.scale,
                             (cy + view.scroll.get_vadjustment().get_value() - view.image_origin[1]) / view.scale)
            event = Gdk.Event.new(Gdk.EventType.SCROLL)
            event.scroll.direction = Gdk.ScrollDirection.DOWN if step[0] == 9 else Gdk.ScrollDirection.UP
            event.scroll.x = cx + view.scroll.get_hadjustment().get_value() - view.visible_origin[0]
            event.scroll.y = cy + view.scroll.get_vadjustment().get_value() - view.visible_origin[1]
            view.events.emit('scroll-event', event)
        elif step[0] in (10, 12):
            view = window.viewer
            assert abs(view.scale - (12.8 if step[0] == 10 else 16)) < .001
            for actual, expected in zip(
                    (view.image_origin[0] + zoom_point[0][0] * view.scale - view.scroll.get_hadjustment().get_value(),
                     view.image_origin[1] + zoom_point[0][1] * view.scale - view.scroll.get_vadjustment().get_value()),
                    (210, 145)):
                assert abs(actual - expected) <= 1, ('cursor zoom drift', actual, expected)
            if step[0] == 12:
                view.scroll.get_hadjustment().set_value(0)
                view.scroll.get_vadjustment().set_value(0)
        elif step[0] == 13:
            view = window.viewer
            assert view.scale == 16
            assert view.picture.get_pixbuf().get_width() <= 3 * view.scroll.get_allocated_width()
            class Event:
                button = 1
                x_root = 400
                y_root = 300
            event = Event()
            view.render()  # Finish the previous zoom/scroll before counting pan work.
            crop = view.picture.get_pixbuf()
            original_render = view.render
            renders, scaled = [], []
            def counted_render():
                renders.append(True)
                previous = view.picture.get_pixbuf()
                result = original_render()
                if view.picture.get_pixbuf() != previous:
                    scaled.append(view.picture.get_pixbuf())
                return result
            view.render = counted_render
            view.press(view.events, event)
            for _ in range(10):
                event.x_root -= 6
                event.y_root -= 4
                view.motion(view.events, event)
            assert not renders, 'pan rescaled synchronously for intermediate pointer positions'
            # A release can contain movement without a preceding motion event.
            event.x_root -= 3
            event.y_root -= 2
            view.release(view.events, event)
            assert view.scroll.get_hadjustment().get_value() == 63
            assert view.scroll.get_vadjustment().get_value() == 42
            while Gtk.events_pending(): Gtk.main_iteration()
            assert len(renders) == 1, ('pan should coalesce both axes and pending motion', len(renders))
            assert view.picture.get_pixbuf() == crop, 'small pan rescaled cached pixels'
            left, top, right, bottom = view.crop_bounds
            assert left <= 63 and top <= 42
            assert right >= min(view.original.get_width() * view.scale, 63 + view.canvas.get_allocated_width())
            assert bottom >= min(view.original.get_height() * view.scale, 42 + view.canvas.get_allocated_height())
            view.render = original_render
            # A wheel burst must paint only its final scale and preserve the
            # source point under the cursor before GTK has allocated anything.
            renders[:] = []
            scaled[:] = []
            view.render = counted_render
            cx, cy = 210.0, 145.0
            source = ((cx + view.scroll.get_hadjustment().get_value() - view.image_origin[0]) / view.scale,
                      (cy + view.scroll.get_vadjustment().get_value() - view.image_origin[1]) / view.scale)
            for factor in (.8, .8, 1.25):
                view.zoom_by(factor, (cx, cy))
            assert not renders, 'wheel burst rescaled intermediate zoom levels'
            while Gtk.events_pending(): Gtk.main_iteration()
            assert len(scaled) == 1, ('wheel burst rescaled more than once', len(scaled))
            assert abs(view.scale - 12.8) < .001
            for axis, adjustment in enumerate((view.scroll.get_hadjustment(), view.scroll.get_vadjustment())):
                actual = view.image_origin[axis] + source[axis] * view.scale - adjustment.get_value()
                assert abs(actual - (cx, cy)[axis]) <= 1, ('burst cursor drift', actual)
            view.render = original_render
            window.browse()
            view.set_zoom(0)
        elif step[0] == 14:
            view = window.viewer
            # Exercise the axis that fills the viewport in either pane layout.
            vw, vh = view.canvas.get_allocated_width(), view.canvas.get_allocated_height()
            axis = 0 if float(vw) / view.original.get_width() < float(vh) / view.original.get_height() else 1
            cx, cy = vw * (.4 if axis == 0 else .5), vh * (.4 if axis == 1 else .5)
            target = (cx, cy)[axis]
            zoom_point[0] = (cx, cy, axis, (target - view.image_origin[axis]) / view.scale)
            event = Gdk.Event.new(Gdk.EventType.SCROLL)
            event.scroll.direction = Gdk.ScrollDirection.UP
            event.scroll.x = cx - view.visible_origin[0]
            event.scroll.y = cy - view.visible_origin[1]
            view.events.emit('scroll-event', event)
        elif step[0] == 15:
            view = window.viewer
            cx, cy, axis, source = zoom_point[0]
            adjustment = (view.scroll.get_hadjustment(), view.scroll.get_vadjustment())[axis]
            actual = view.image_origin[axis] + source * view.scale - adjustment.get_value()
            assert abs(actual - (cx, cy)[axis]) <= 1, ('fit-to-zoom cursor drift', actual, (cx, cy)[axis])
            assert adjustment.get_upper() > adjustment.get_page_size()
            event = Gdk.Event.new(Gdk.EventType.SCROLL)
            event.scroll.direction = Gdk.ScrollDirection.DOWN
            event.scroll.x = cx + view.scroll.get_hadjustment().get_value() - view.visible_origin[0]
            event.scroll.y = cy + view.scroll.get_vadjustment().get_value() - view.visible_origin[1]
            view.events.emit('scroll-event', event)
        elif step[0] == 16:
            import runpy
            runpy.run_path('/home/test/nix/apps/painter/tools/text-history-gtk-test.py', init_globals={'parent': window})
            original_send, stops = window.send, []
            window.send = lambda op, **kwargs: stops.append(op)
            try:
                window.actions['cancel'][-1].emit('clicked')
                event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
                event.button.button, event.button.time = 3, Gdk.CURRENT_TIME
                assert window.actions['cancel'][-1].get_child().emit('button-press-event', event)
                window.stop_menu.get_children()[0].activate()
                window.stop_menu.popdown()
                assert stops == ['cancel', 'hard_stop']
            finally:
                window.send = original_send
            current = dict(window.values())
            before_viewport = (window.viewer.get_allocated_width(), window.viewer.get_allocated_height())
            window.toggle_parameter_compare()
            while Gtk.events_pending(): Gtk.main_iteration()
            import copy
            saved = copy.deepcopy(window.state)
            saved['settings']['positive'] = 'Saved prompt'
            saved['settings']['steps'] = 17
            import moss_layout
            document = moss_layout.Editor(moss_layout.fresh(640, 768, 'Saved prompt'))
            document.add('object')['caption'] = 'Saved region'
            saved['settings']['moss_layout'] = document.doc
            saved['settings']['negpip'] = True
            saved['flags']['layoutSupport'] = True
            window.receive_parameter_compare(dict(path=window.selection, snapshot=saved))
            while Gtk.events_pending(): Gtk.main_iteration()
            compare_x, compare_y = window.compare_panel.translate_coordinates(window.parameter_overlay, 0, 0)
            current_x, current_y = window.params_scroll.translate_coordinates(window.parameter_overlay, 0, 0)
            assert compare_x >= current_x + window.params_scroll.get_allocated_width(), (
                'comparison overlaps current settings', compare_x, current_x, window.params_scroll.get_allocated_width())
            assert window.compare_panel.get_allocated_width() == window.params_scroll.get_allocated_width()
            assert (window.viewer.get_allocated_width(), window.viewer.get_allocated_height()) == before_viewport
            form = window.compare_form
            assert form.ppm.get_visible() and form.ppm.get_active()
            assert form.ppm.get_parent() is form.sampling.get_child()
            form.ppm.set_active(False)
            assert form.values()['negpip'] is False
            assert set(form.controls) == set(window.controls)
            assert set(form.rows) == set(window.rows)
            text = form.controls['positive']
            assert window.compare_scroll.get_visible()
            buf = text.get_buffer()
            buf.select_range(buf.get_start_iter(), buf.get_end_iter())
            assert buf.get_has_selection()
            assert form.values()['positive'] == 'Saved prompt'
            form.controls['steps'].set_value(19)
            assert form.values()['steps'] == 19
            assert form.layout_editor is not window.layout_editor, form.status.get_text()
            assert form.layout_editor.ui.window is form
            assert form.layout_doc['items'][0]['caption'] == 'Saved region'
            form.layout_editor.ui.set(form.layout_editor.fields['summary.meta'], 'saved medium')
            assert window.values() == current
            window.toggle_parameter_compare()
            assert not window.compare_panel.get_visible()
            original = dict(window.state)
            for rate, expected in [(2.5, '2.50 it/s'), (.25, '4.00 s/it'), (0, '')]:
                state = dict(original, busy=True, progress=.42, elapsed=125, rate=rate)
                window.receive('poll', dict(ok=True, state=state))
                assert window.status.get_text().decode('utf-8').startswith('2:05   |')
                assert window.progress.get_text() == '42%' + ('   |   ' + expected if expected else '')
            window.receive('poll', dict(ok=True, state=original))
            assert window.progress.get_text() == ''
            import runpy
            runpy.run_path('/home/test/nix/apps/painter/tools/layout-gtk-test.py', init_globals={'parent': window})
            view = window.viewer
            cx, cy, axis, source = zoom_point[0]
            adjustment = (view.scroll.get_hadjustment(), view.scroll.get_vadjustment())[axis]
            actual = view.image_origin[axis] + source * view.scale - adjustment.get_value()
            assert abs(actual - (cx, cy)[axis]) <= 1, ('zoom-to-fit cursor drift', actual, (cx, cy)[axis])
            window.view()
            old = window.selection
            index = next(i for i, row in enumerate(window.tiles) if row[2] == old)
            window.walk(-1 if index else 1)
            assert window.selection != old
            select('fixture.png')
            window.browse()
            while Gtk.events_pending(): Gtk.main_iteration()
            window.browse_pane.set_position(window.browse_pane.get_allocated_width() - 10 - 240)
            while Gtk.events_pending(): Gtk.main_iteration()
            assert window.history_size() == 240
            window.controls['positive'].get_buffer().set_text('last edit before closing')
            window.close_window()
            print('PASS: GTK 3.6 controls, resized prompts, fit/zoom/compare, muted video, Browse/View, global menu')
            return False
        step[0] += 1
        return True
    except Exception:
        traceback.print_exc()
        failed[0] = True
        window.connection.close()
        Gtk.main_quit()
        return False
GLib.timeout_add(1200, test)
Gtk.main()
if not failed[0]:
    window = Window(sys.argv[1])
    window.resize(1180, 780)
    def reopened():
        if not window.state.get('model'):
            return True
        try:
            assert window.text_boxes['positive'].height == 285
            assert window.text_boxes['negative'].height == 40
            assert window.text_boxes['system_prompt'].height == 600
            assert window.values()['positive'] == 'last edit before closing'
            assert window.history_size() == 240, window.history_size()
            assert window.state['historyWidth'] == 240
            assert window.history_scroll.get_allocated_width() == 240
            assert not window.sampling.get_expanded()
            window.sampling.set_expanded(True)
            assert window.sampling.get_expanded()
            assert window.sidebar_split.get_position() == 440, (window.sidebar_split.get_position(), window.placement_grid.get_preferred_width(), [(key, window.controls[key].get_preferred_width()) for key in ('seed', 'aspectW', 'aspectH', 'megapixels')])
            assert window.state['sidebarWidth'] == 440
            assert window.layout_height == 380
            assert window.region_list_height >= 80
            assert window.region_prompt_height > 95
            print('PASS: prompt heights and text survive closing and reopening')
        except Exception:
            traceback.print_exc()
            failed[0] = True
        window.close_window()
        return False
    GLib.timeout_add(500, reopened)
    Gtk.main()
raise SystemExit(1 if failed[0] else 0)
