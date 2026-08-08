# free-handles.py — loaded by the `watcher` line in kitty.conf, which runs this
# file inside the kitty process (kitty's sanctioned in-process extension point;
# a load failure is logged to stderr, never fatal). It defines no watcher
# hooks: the whole point is the top-level monkeypatch below.
#
# Stock kitty stores `splits`-layout windows as a binary tree of Pair nodes,
# and dragging a border adjusts one node's bias — so every border nested
# inside both halves of that node slides proportionally with the drag, and a
# nested border doesn't even track the pointer 1:1 (the increment is scaled to
# the whole tab area while bias is a fraction of the pair's own region).
# However the splits were created, moving one handle is supposed to move that
# handle: the replacement converts the drag to pixels so the grabbed border
# follows the pointer exactly, then recomputes every affected descendant
# pair's bias from its recorded geometry so each other border keeps its
# absolute screen position. The tree stays the data model; the handles stop
# behaving like one. Harness: ~/nix/tools/kitty-free-handles-test.py.
#
# Keyboard resizing (the `resize_window` action) keeps stock tree semantics —
# only border drags go through drag_resize_window.

import os


def _install() -> None:
    from kitty.layout.base import lgd
    from kitty.layout.splits import Pair, Splits

    def _pin(node, horizontal, dpx, leading_edge_moved):
        # node's region just gained/lost dpx pixels on one edge of the drag
        # axis; rewrite biases so every border inside it stays where it was.
        # Geometry (left/top/width/height) is what the last layout recorded —
        # drags happen between relayouts, so it is current.
        while isinstance(node, Pair):
            if node.one is None or node.two is None:
                # redundant pair: the sole child owns the whole region
                node = node.one if node.one is not None else node.two
                continue
            if node.horizontal is not horizontal:
                # splits along the other axis: its own border is unaffected,
                # both children share the moved edge
                _pin(node.one, horizontal, dpx, leading_edge_moved)
                node = node.two
                continue
            edge, span = (node.left, node.width) if horizontal else (node.top, node.height)
            if span <= 0:
                return
            border = edge + node.bias * span
            if leading_edge_moved:
                edge, span, nxt = edge + dpx, span - dpx, node.one
            else:
                span, nxt = span + dpx, node.two
            if span <= 0:
                return
            node.bias = max(0.0, min((border - edge) / span, 1.0))
            # only the child touching the moved edge changed size
            node = nxt

    def drag_resize_window(self, all_windows, window_id, increment, is_horizontal=True):
        for pair in self.pairs_root.self_and_descendants():
            if id(pair) == window_id:
                break
        else:
            return False
        # increment arrives as a fraction of the whole central area
        # (tabs.drag_resize_window multiplies the cell steps by
        # bias_increment_for_cell); pair.bias is a fraction of the pair's own
        # region — go through pixels so the border moves as far as the pointer.
        if is_horizontal:
            dpx = increment * lgd.central.width
            span = pair.width
        else:
            dpx = increment * lgd.central.height
            span = pair.height
        if span <= 0:
            return False
        new_bias = max(0.0, min(pair.bias + dpx / span, 1.0))
        if new_bias == pair.bias:
            return False
        dpx = (new_bias - pair.bias) * span  # only what the clamp let through
        pair.bias = new_bias
        _pin(pair.one, is_horizontal, dpx, leading_edge_moved=False)
        _pin(pair.two, is_horizontal, dpx, leading_edge_moved=True)
        return True

    Splits.drag_resize_window = drag_resize_window
    if os.environ.get('FREE_HANDLES_DEBUG'):
        from kitty.utils import log_error
        log_error('free-handles: installed')


try:
    _install()
except Exception:
    import traceback

    from kitty.utils import log_error
    log_error('free-handles.py: could not patch splits drag-resize, stock behaviour kept:\n'
              + traceback.format_exc())
