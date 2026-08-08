#!/usr/bin/env python3
# Harness for home/prog/kitty-files/free-handles.py — the kitty watcher that
# makes splits-layout border drags move only the grabbed handle.
#
# Runs against the INSTALLED kitty's own layout code (so it tests whatever
# version this host actually runs, on top and book alike): if kitty's modules
# aren't importable it re-execs itself under `kitty +runpy`. Headless — no
# window, no display, nothing near the live session.
#
# What it proves:
#   1. stock drag_resize_window tree-couples nested borders (if this ever
#      stops failing, upstream fixed it and the watcher is obsolete — retire it)
#   2. the watcher loads the way kitty loads it (runpy, __kitty_watcher__)
#   3. a drag moves the grabbed border 1:1 with the pointer's cell steps
#   4. every other border keeps its absolute position (nested same-axis,
#      cross-axis subtrees, vertical drags)
#   5. overshoot clamps sanely, biases stay in [0, 1]

import os
import sys

try:
    import kitty.layout.splits  # noqa: F401
except ImportError:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.environ['FH_REPO_ROOT'] = root
    me = os.path.abspath(__file__)
    # +runpy exec()s its argument inside a function frame, where top-level
    # defs don't become globals — compile the file into a fresh module-style
    # namespace instead
    os.execvp('kitty', ['kitty', '+runpy',
                        f'exec(compile(open({me!r}).read(), {me!r}, "exec"), {{"__name__": "__main__"}})'])

import runpy

import kitty.layout.base as base
from kitty.fast_data_types import Region
from kitty.layout.splits import Pair, Splits

REPO_ROOT = os.environ.get('FH_REPO_ROOT') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHER = os.path.join(REPO_ROOT, 'home', 'prog', 'kitty-files', 'free-handles.py')

CW, CH = 8, 15
W, H = 1600, 900
base.lgd.central = Region((0, 0, W - 1, H - 1, W, H))
base.lgd.cell_width, base.lgd.cell_height = CW, CH

failures = []


def check(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL') + f': {name}' + (f'  [{detail}]' if detail and not cond else ''))
    if not cond:
        failures.append(name)


def pair(horizontal, one, two, bias=0.5):
    p = Pair(horizontal=horizontal)
    p.one, p.two, p.bias = one, two, bias
    return p


def relayout(p, left, top, width, height, borders):
    """Mirror of Pair.layout_pair's arithmetic (border width 0, no minimum
    sizes): record each pair's region the way kitty does, and each split
    line's absolute position keyed by the pair that owns it."""
    p.left, p.top, p.width, p.height = left, top, width, height
    if p.one is None or p.two is None:
        q = p.one if p.one is not None else p.two
        if isinstance(q, Pair):
            relayout(q, left, top, width, height, borders)
        return
    if p.horizontal:
        w1 = int(p.bias * width)
        borders[id(p)] = left + w1
        halves = ((p.one, left, top, w1, height), (p.two, left + w1, top, width - w1, height))
    else:
        h1 = int(p.bias * height)
        borders[id(p)] = top + h1
        halves = ((p.one, left, top, width, h1), (p.two, left, top + h1, width, height - h1))
    for child, cl, ct, cw, ch in halves:
        if isinstance(child, Pair):
            relayout(child, cl, ct, cw, ch, borders)


def layout_of(root):
    borders = {}
    relayout(root, 0, 0, W, H, borders)
    return borders


def splits_for(root):
    s = Splits.__new__(Splits)
    s._pairs_root = root
    return s


def increment_for_cells(n, is_horizontal):
    # what tabs.drag_resize_window hands the layout for n whole-cell steps
    return n * ((CW + 1) / W if is_horizontal else (CH + 1) / H)


def drag(root, target, cells, is_horizontal=True):
    before = layout_of(root)
    moved = splits_for(root).drag_resize_window(None, id(target), increment_for_cells(cells, is_horizontal), is_horizontal)
    after = layout_of(root)
    return moved, before, after


def three_columns():
    inner = pair(True, 2, 3)
    return pair(True, 1, inner), inner


# -- 1. the stock behaviour this exists to replace ---------------------------
stock = Splits.drag_resize_window
root, inner = three_columns()
_, before, after = drag(root, root, 5)
check('stock tree-couples the nested border (else the watcher is obsolete)',
      after[id(inner)] != before[id(inner)])

# -- 2. load the watcher exactly the way kitty does --------------------------
runpy.run_path(WATCHER, run_name='__kitty_watcher__')
check('watcher replaced Splits.drag_resize_window', Splits.drag_resize_window is not stock)

# -- 3. the grabbed border tracks the pointer 1:1 ----------------------------
root, inner = three_columns()
moved, before, after = drag(root, inner, 2)
dpx = 2 * (CW + 1)
check('drag reports a resize', moved)
check('nested border moves by the pointer delta, not bias-scaled',
      abs(after[id(inner)] - before[id(inner)] - dpx) <= 1,
      f'moved {after[id(inner)] - before[id(inner)]}px, wanted {dpx}px')
check('outer border stays put', after[id(root)] == before[id(root)])

# -- 4. dragging the outer border pins the nested one ------------------------
root, inner = three_columns()
_, before, after = drag(root, root, 5)
check('outer border moves', abs(after[id(root)] - before[id(root)] - 5 * (CW + 1)) <= 1)
check('nested same-axis border keeps its screen position',
      abs(after[id(inner)] - before[id(inner)]) <= 1,
      f'drifted {after[id(inner)] - before[id(inner)]}px')

# deep mixed tree: A | (B / (C | D)) — drag the root, the C|D border is two
# levels down behind a cross-axis pair and must still not drift
cd = pair(True, 3, 4)
bv = pair(False, 2, cd)
root = pair(True, 1, bv)
_, before, after = drag(root, root, 5)
check('border behind a cross-axis pair keeps its screen position',
      abs(after[id(cd)] - before[id(cd)]) <= 1)
check('cross-axis border unaffected by a horizontal drag',
      after[id(bv)] == before[id(bv)])

# vertical drags, nested same-axis vertical pairs
vin = pair(False, 2, 3)
root = pair(False, 1, vin)
_, before, after = drag(root, root, 3, is_horizontal=False)
check('vertical: outer border moves', abs(after[id(root)] - before[id(root)] - 3 * (CH + 1)) <= 1)
check('vertical: nested border keeps its screen position',
      abs(after[id(vin)] - before[id(vin)]) <= 1)

# -- 5. overshoot ------------------------------------------------------------
root, inner = three_columns()
drag(root, root, 10000)
biases = [p.bias for p in root.self_and_descendants()]
check('overshoot clamps, biases stay in [0,1]', all(0.0 <= b <= 1.0 for b in biases))
_, b2, a2 = drag(root, root, -3)
check('drag back from the clamp still works', a2[id(root)] < b2[id(root)])

print()
if failures:
    print(f'{len(failures)} FAILED: ' + ', '.join(failures))
    sys.exit(1)
print('all tests passed')
