# -*- coding: utf-8 -*-
"""Loaded only by unity-gtk-test.py in its private display namespace."""
from __future__ import unicode_literals
import os
assert os.environ['HOME'] == '/home/test' and os.environ['DISPLAY'] == ':93'
from gi.repository import Gtk, Gdk
import moss_layout as M
from layout_gtk import open_editor


def run(parent):
    # Force LCD antialiasing through fontconfig in the harness. A white glyph
    # on transparency must still have equal RGB channels after rasterization.
    settings = Gtk.Settings.get_default()
    settings.set_property('gtk-xft-antialias', 1)
    settings.set_property('gtk-xft-rgba', 'bgr')
    while Gtk.events_pending(): Gtk.main_iteration()
    from layout_raster import rasterize
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="40"><g transform="translate(1.3,2.4)"><defs><clipPath id="label"><rect width="200" height="40"/></clipPath></defs><text clip-path="url(#label)" x="3" y="25" fill="white" font-family="Ubuntu" font-size="14">White region text</text></g></svg>'
    pix = rasterize(svg, 200, 40)
    pixels = bytearray(pix.get_pixels())
    assert any(pixels[3::4]), 'text was not rendered'
    assert all(pixels[i] == pixels[i+1] == pixels[i+2] for i in range(0, len(pixels), 4)), 'coloured fringes on white text'
    coloured = svg.replace(b'</svg>', b'<rect x="190" y="0" width="10" height="40" fill="#79bfff"/></svg>')
    colour_pix = rasterize(coloured, 200, 40)
    rgb = bytearray(colour_pix.get_pixels())
    offset = 20 * colour_pix.get_rowstride() + 195 * 4
    assert rgb[offset:offset+4] == bytearray([0x79, 0xbf, 0xff, 255]), 'text mask changed guide colours'
    muted = rasterize(svg.replace(b'fill="white"', b'fill="#888888"'), 200, 40)
    muted_pixels = bytearray(muted.get_pixels())
    assert all(muted_pixels[i] == muted_pixels[i+1] == muted_pixels[i+2] for i in range(0, len(muted_pixels), 4)), 'fringes on inactive lettering'
    assert any(muted_pixels[i+3] == 255 and muted_pixels[i] == 136 for i in range(0, len(muted_pixels), 4)), 'inactive text colour ignored'
    accepted = []
    initial_width = parent.get_allocated_width()
    before_windows = [w for w in Gtk.Window.list_toplevels() if w.get_visible()]
    parent.layout_box.show()
    e = open_editor(parent.layout_box, M.fresh(caption='A travel poster'), accepted.append)
    assert [w for w in Gtk.Window.list_toplevels() if w.get_visible()] == before_windows
    assert e.canvas.get_toplevel() is parent
    assert e.side.get_visible()
    assert e.add_button.get_image() is not None
    assert e.add_button.get_tooltip_text() == 'Add region'
    assert not e.list.region_box.get_visible()
    u = e.ui
    tabs = e.tabs
    assert not e.fields['item.caption'][2].get_visible()
    assert not e.fields['item.tags'][2].get_visible()
    assert not e.fields['item.palette'][2].get_visible()
    assert e.warning.get_visible()
    while Gtk.events_pending(): Gtk.main_iteration()
    tabs.set_current_page(1)
    while Gtk.events_pending(): Gtk.main_iteration()
    assert not e.canvas.is_drawable(), 'region canvas visible on Scene tab'
    scene_height = e.side.get_preferred_height()[1]
    tabs.set_current_page(2)
    while Gtk.events_pending(): Gtk.main_iteration()
    assert not e.canvas.is_drawable(), 'region canvas visible on Canvas tab'
    assert e.side.get_preferred_height()[1] != scene_height, 'inspector reserves height for inactive pages'
    tabs.set_current_page(0)
    saved_values, saved_settings = parent.values(), parent.state['settings']
    saved_doc, saved_loading = parent.layout_doc, parent.loading
    parent.loading = True
    mp_digits = parent.controls['megapixels'].get_digits()
    try:
        mp = parent.controls['megapixels']
        mp.set_digits(6)
        for value, display in [(1.0, '1'), (1.6, '1.6'), (.998656, '0.998656')]:
            mp.set_value(value)
            assert mp.get_text() == display, mp.get_text()
        parent.state['settings'] = dict(saved_settings, width=1328, height=752)
        for key, value in [('aspectW', 16), ('aspectH', 9), ('megapixels', 1.0)]:
            parent.controls[key].set_value(value)
        parent.layout_changed(M.fresh(1328, 752, 'Edited region'))
        values = parent.values()
        assert (values['aspectW'], values['aspectH'], values['megapixels']) == (16, 9, 1.0)
        parent.layout_changed(M.fresh(1600, 1000, 'Resized canvas'))
        values = parent.values()
        assert (values['aspectW'], values['aspectH'], values['megapixels']) == (8, 5, 1.6)
    finally:
        parent.controls['megapixels'].set_digits(mp_digits)
        parent.state['settings'], parent.layout_doc = saved_settings, saved_doc
        for key in ('aspectW', 'aspectH', 'megapixels'):
            parent.controls[key].set_value(saved_values[key])
        parent.controls['positive'].get_buffer().set_text(saved_values['positive'])
        parent.loading = saved_loading
    from spelling_gtk import Spelling, text
    requests = []
    checker = Spelling(requests.append)
    for control in (Gtk.TextView(), Gtk.Entry()):
        field = checker.attach(control)
        if isinstance(control, Gtk.TextView): control.get_buffer().set_text('é helo world')
        else: control.set_text('é helo world')
        field.check()
        assert requests[-1]['text'] == 'é helo world'
        result = dict(field=field.identity, text='é helo world', words=[dict(start=2, end=6, word='helo', suggestions=['hello'])])
        checker.receive(result)
        if isinstance(control, Gtk.TextView):
            assert field.tag in control.get_buffer().get_iter_at_offset(3).get_tags()
        else:
            assert control.get_attributes() is not None
        field.position = 3
        menu = Gtk.Menu()
        field.menu(control, menu)
        assert menu.get_children()[0].get_label() == 'hello'
        menu.get_children()[0].activate()
        assert text(control) == 'é hello world'
        checker.receive(result)
        assert field.checked == 'é helo world', 'stale result changed the checked text'
        menu.destroy()
        control.destroy()
    assert all(any(f.control is parent.controls[key] for f in parent.spelling.fields.values()) for key in ('positive', 'negative', 'system_prompt'))
    while Gtk.events_pending(): Gtk.main_iteration()
    assert e.canvas.get_parent() is tabs.pages[0]
    children = tabs.pages[0].get_children()
    assert children.index(e.list.region_box) < children.index(e.canvas)
    original_height = e.canvas.get_allocated_height()
    for signal, kind, y in [('button-press-event', Gdk.EventType.BUTTON_PRESS, 100),
                            ('motion-notify-event', Gdk.EventType.MOTION_NOTIFY, 180),
                            ('button-release-event', Gdk.EventType.BUTTON_RELEASE, 180)]:
        event = Gdk.Event.new(kind)
        if kind == Gdk.EventType.MOTION_NOTIFY:
            event.motion.y_root = y
        else:
            event.button.button = 1
            event.button.y_root = y
        e.canvas.resize_handle.emit(signal, event)
    assert e.canvas.get_size_request()[1] == original_height + 80
    assert not e.canvas.resize_handle.has_grab()
    assert parent.layout_height == original_height + 80
    reopened = open_editor(parent.layout_box, M.fresh(), accepted.append)
    assert reopened.canvas.get_size_request()[1] == original_height + 80
    reopened.ui.close()
    e.canvas.set_size_request(180, original_height)
    while Gtk.events_pending(): Gtk.main_iteration()
    parent.params_scroll.get_vadjustment().set_value(parent.layout_box.get_allocation().y)
    u.set(e.tool, 'text')
    e.add_button.clicked()
    assert e.model.tool == 'text'
    ox, oy, w, h = e.rect
    for kind, x, y in [(Gdk.EventType.BUTTON_PRESS, -5 / w, .2), (Gdk.EventType.MOTION_NOTIFY, 1.2, .5), (Gdk.EventType.BUTTON_RELEASE, .7, .5)]:
        event = Gdk.Event.new(kind)
        if kind == Gdk.EventType.MOTION_NOTIFY:
            event.motion.x, event.motion.y = ox + x * w, oy + y * h
            event.motion.state = Gdk.ModifierType.BUTTON1_MASK
            e.canvas.emit('motion-notify-event', event)
        else:
            event.button.button = 1
            event.button.x, event.button.y = ox + x * w, oy + y * h
            e.canvas.emit('button-press-event' if kind == Gdk.EventType.BUTTON_PRESS else 'button-release-event', event)
    assert len(e.model.doc['items']) == 1
    assert e.list.region_box.get_visible()
    assert e.list.region_scroll.get_size_request()[1] < 80
    assert e.model.tool == 'select' and e.side.get_visible()
    e.buttons['Lock'].clicked()
    assert not e.model.selected and e.model.doc['items'][0]['locked']
    e.selection_changed([e.model.doc['items'][0]['id']])
    e.buttons['Lock'].clicked()
    assert not e.model.chosen()[0]['locked']
    e.buttons['Hide'].clicked()
    assert not e.model.chosen()[0]['enabled']
    e.buttons['Hide'].clicked()
    assert e.model.chosen()[0]['enabled']
    while Gtk.events_pending(): Gtk.main_iteration()
    ox, oy, w, h = e.rect
    box = e.model.chosen()[0]['box']
    x, y = ox + (box[0] + box[2] / 2) * w, oy + (box[1] + box[3] / 2) * h
    e.pointer('press', x, y)
    while Gtk.events_pending(): Gtk.main_iteration()
    renders, render = [], e.render
    def counted(*args):
        renders.append(list(e.model.chosen()[0]['box']))
        return render(*args)
    e.render = counted
    before_save = len(accepted)
    try:
        for n in range(1, 21): e.pointer('move', x + w * n / 200.0, y)
        assert not renders, 'drag rendered synchronously for each motion'
        assert len(accepted) == before_save, 'drag saved intermediate positions'
        e.pointer('release', x + w * .1, y)
        while Gtk.events_pending(): Gtk.main_iteration()
        assert len(renders) == 1, ('motion burst was not coalesced', len(renders))
        assert renders[0] == e.model.chosen()[0]['box'], 'final drag position was not rendered'
        assert len(accepted) == before_save + 1, 'final drag position was not saved'
    finally:
        e.render = render
    assert 'item.locked' not in e.fields and 'item.enabled' not in e.fields
    for signal, kind, y in [('button-press-event', Gdk.EventType.BUTTON_PRESS, 100),
                            ('motion-notify-event', Gdk.EventType.MOTION_NOTIFY, 180),
                            ('button-release-event', Gdk.EventType.BUTTON_RELEASE, 180)]:
        event = Gdk.Event.new(kind)
        if kind == Gdk.EventType.MOTION_NOTIFY: event.motion.y_root = y
        else:
            event.button.button = 1
            event.button.y_root = y
        e.list.resize_handle.emit(signal, event)
    assert parent.region_list_height >= 80
    assert e.list.region_scroll.get_size_request()[1] == parent.region_list_height

    toolbar = e.add_button.get_parent()
    assert e.buttons['Duplicate'].get_parent() is toolbar
    assert e.buttons['Undo'].get_parent() is toolbar
    assert e.buttons['Delete'].get_parent() is toolbar
    coordinates = e.units[2].get_parent()
    holder = coordinates.get_parent()
    minimum, natural = toolbar.get_preferred_width()
    assert natural - minimum >= coordinates.get_preferred_width()[0]
    assert parent.params_scroll.get_preferred_width()[0] <= minimum + 42, (
        'another sidebar control prevents compact toolbar sizing', minimum,
        parent.params_scroll.get_preferred_width()[0])
    allocation = toolbar.get_allocation()
    saved_width = allocation.width
    allocation.width = minimum
    toolbar.size_allocate(allocation)
    assert not coordinates.get_child_visible(), 'coordinates prevented toolbar shrinking'
    buttons = [e.add_button] + [e.buttons[k] for k in ('Clear all', 'Undo', 'Redo', 'Hide', 'Lock', 'Delete', 'Duplicate')]
    assert all(b.get_allocated_width() >= b.get_preferred_width()[0] for b in buttons)
    allocation.width = natural + 100
    toolbar.size_allocate(allocation)
    assert coordinates.get_child_visible(), ('coordinates did not return at wide width', minimum, natural,
        holder.get_preferred_width(), holder.get_allocated_width(), coordinates.get_preferred_width())
    allocation.width = saved_width
    toolbar.size_allocate(allocation)
    row = e.model.doc['items'][0]
    assert row['label'] == 'text' and abs(row['box'][2] - .7) < .02
    u.set(e.tool, 'character')
    assert e.model.chosen()[0]['label'] == 'character'
    u.set(e.tool, 'text')
    assert e.model.chosen()[0]['label'] == 'text'
    u.set(e.fields['summary.meta'], 'poster, illustration')
    u.set(e.fields['summary.palette'], '#ffffff, #123456')
    assert e.fields['item.caption'][2].get_visible()
    u.set(e.fields['item.caption'], 'Large heading')
    parent.layout_box.show()
    while Gtk.events_pending(): Gtk.main_iteration()
    parent.layout_box.show()
    parent.check_resize()
    prompt = e.fields['item.caption'][1]
    for signal, kind, y in [('button-press-event', Gdk.EventType.BUTTON_PRESS, 100),
                            ('motion-notify-event', Gdk.EventType.MOTION_NOTIFY, 180),
                            ('button-release-event', Gdk.EventType.BUTTON_RELEASE, 180)]:
        event = Gdk.Event.new(kind)
        if kind == Gdk.EventType.MOTION_NOTIFY: event.motion.y_root = y
        else:
            event.button.button = 1
            event.button.y_root = y
        prompt.resize_handle.emit(signal, event)
    assert parent.region_prompt_height > 95, (parent.region_prompt_height, e.tabs.get_current_page(), [p.get_visible() for p in e.tabs.pages], prompt.get_allocated_height(), parent.layout_box.get_visible())
    u.set(e.fields['item.text'], 'HELLO')
    wording = e.fields['item.text'][1]
    parent.browse()
    parent.layout_box.show()
    e.tabs.set_current_page(0)
    wording.grab_focus()
    while Gtk.events_pending(): Gtk.main_iteration()
    # The fixture's non-MOSS settings poll hides this manually attached editor.
    parent.layout_box.show()
    wording.grab_focus()
    assert wording.get_realized() and wording.get_mapped()
    assert parent.get_focus() is wording
    wording.get_buffer().place_cursor(wording.get_buffer().get_end_iter())
    before_page = parent.pages.get_current_page()
    event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    event.key.window = wording.get_window(Gtk.TextWindowType.TEXT)
    event.key.keyval = Gdk.KEY_Return
    event.key.state = Gdk.ModifierType(0)
    event.key.send_event = True
    parent.emit('key-press-event', event)
    assert u.get(e.fields['item.text']) == 'HELLO\n', 'Enter was stolen from Exact wording'
    assert parent.pages.get_current_page() == before_page
    u.set(e.fields['item.text'], 'HELLO\n世界')
    u.set(e.fields['type.family'], 'serif')
    u.set(e.fields['type.color'], '#123456')
    u.set(e.fields['type.outline'], 'thin white outline')
    u.set(e.fields['type.shadow'], 'soft grey shadow')
    u.set(e.fields['type.surface'], 'painted wooden sign')
    u.set(e.fields['item.palette'], '#abcdef')
    u.set(e.fields['item.tags'], 'title, lettering')
    u.set(e.fields['enabled'], True)
    u.set(e.units, 'pixels')
    u.set(e.fields['box.position'], '128, 256')
    e.fields['box.position'][1].emit('activate')
    assert e.model.doc['items'][0]['box'][0] == .125
    e.buttons['Lock'].clicked()
    assert not e.fields['box.position'][2].get_sensitive()
    e.selection_changed([e.model.doc['items'][0]['id']])
    e.set_reference('/home/test/out/fixture.png')
    e.refresh()
    assert e.reference, 'reference image must load in GTK 3.6'
    underlay = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="20" height="20"><image width="20" height="20" preserveAspectRatio="none" xlink:href="data:image/png;base64,%s"/></svg>' % e.reference).encode('utf-8')
    underlay_pix = rasterize(underlay, 20, 20)
    offset = 10 * underlay_pix.get_rowstride() + 10 * underlay_pix.get_n_channels()
    assert bytearray(underlay_pix.get_pixels())[offset:offset+3] == bytearray([255, 0, 0]), 'reference underlay lost in rasterization'
    assert b'data:image/png;base64,' in e.render(700, 600)
    copied = []
    u.copy = copied.append
    u.paste = lambda: copied[0]
    e.copy(); e.paste()
    assert len(e.model.doc['items']) == 2
    e.model.undo(); assert len(e.model.doc['items']) == 1
    u.set(e.fields['custom_x'], '20, 80')
    u.set(e.fields['custom_y'], '25, 75')
    assert e.model.doc['custom_x'] == [.2,.8]
    while Gtk.events_pending(): Gtk.main_iteration()
    assert parent.get_allocated_width() == initial_width, 'inline inspector enlarged the main window'
    window = u.window.get_window()
    pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, u.window.get_allocated_width(), u.window.get_allocated_height())
    pixbuf.savev('/home/test/layout.png', 'png', [], [])
    e.publish()
    assert accepted and accepted[-1]['enabled']
    compiled = M.compile(accepted[-1])
    assert 'HELLO' in compiled and 'reference' not in compiled
    doc = M.valid(e.model.doc)
    doc['summary']['caption'] = 'Reloaded scene'
    e.load(doc)
    e.selection_changed([e.model.doc['items'][0]['id']])
    e.buttons['Delete'].clicked()
    assert not e.model.doc['items']
    e.ui.close()
    parent.browse()
    print('PASS: GTK inline layout drawing, text, palettes, geometry locks, guides, underlay, copy and autosave')

if 'parent' in globals():
    run(parent)
