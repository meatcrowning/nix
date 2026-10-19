# -*- coding: utf-8 -*-
"""Weight shortcuts for the native main and region prompt editors (GTK 3.6)."""
from __future__ import unicode_literals
import re
from gi.repository import Gdk
from text_history_gtk import snapshot


def key(control, event):
    if (not event.state & Gdk.ModifierType.CONTROL_MASK or
            event.keyval not in (Gdk.KEY_Up, Gdk.KEY_Down) or not control.get_editable()):
        return False
    text, cursor, anchor = snapshot(control)
    start, end = sorted((cursor, anchor))
    if start == end:
        def separator(i):
            return text[i] in ',\n()|:' and not (text[i] in '()' and i and text[i-1] == '\\')
        while start > 0 and not separator(start-1): start -= 1
        while end < len(text) and not separator(end): end += 1
        while start < end and text[start] == ' ': start += 1
        while end > start and text[end-1] == ' ': end -= 1
        if not start <= cursor <= end: return False
    body = text[start:end]
    if not body.strip(): return False
    before = start - 1
    while before >= 0 and text[before] == ' ': before -= 1
    weight, first, last = 1.0, start, end
    if before >= 0 and text[before] == '(' and not (before and text[before-1] == '\\'):
        match = re.match(r'\s*(?::\s*(-?\d*\.?\d+)\s*)?\)', text[end:])
        if match:
            first, last = before, end + match.end()
            weight = float(match.group(1)) if match.group(1) else 1.0
    weight = max(-4, min(4, round(weight + (.1 if event.keyval == Gdk.KEY_Up else -.1), 2)))
    replacement = body if weight == 1 else '(' + body + ':%.2f)' % weight
    history = getattr(control, '_text_history', None)
    if history: history.flush()
    buf = control.get_buffer()
    buf.begin_user_action()
    buf.set_text(text[:first] + replacement + text[last:])
    offset = first + (0 if weight == 1 else 1)
    buf.select_range(buf.get_iter_at_offset(offset + len(body)), buf.get_iter_at_offset(offset))
    buf.end_user_action()
    if history: history.flush()
    return True


def attach(control):
    control.connect('key-press-event', key)
