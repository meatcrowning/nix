#!/usr/bin/env python3
"""Headless checks for Painter's prompt wildcard expansion."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wildcards as W  # noqa: E402


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"ok  {label}")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "colour.txt").write_text("# ignored\nred\n\nblue\n", encoding="utf-8")
    (root / "pose.txt").write_text("standing\nsitting\n", encoding="utf-8")
    (root / "bad name.txt").write_text("unused", encoding="utf-8")
    check("button names match supported wildcard tokens", W.names(root) == ['colour', 'pose'])

    first = W.expand("a __colour__ cube", 4242, root)
    check("a fixed seed is repeatable", first == W.expand("a __colour__ cube", 4242, root))
    check("the token is replaced", "__colour__" not in first)
    check("comments and blanks are ignored", first in {"a red cube", "a blue cube"})
    check("unknown names remain visible", W.expand("__missing__", 1, root) == "__missing__")

    pos, neg = W.expand_prompts("__pose__, __colour__", "not __colour__", 99, root)
    check("both prompt boxes expand", "__" not in pos and "__" not in neg)
    check("one name has one pick across both boxes", pos.split(", ")[1] == neg[4:])

    import copy
    import moss_layout as M
    editor = M.Editor(M.fresh(1024, 1024, 'A poster'))
    region = editor.add('object')
    region['caption'] = 'A __colour__ cube beside a __missing__ object'
    text = editor.add('text')
    text.update(caption='__colour__ lettering', text='__colour__')
    editor.doc['enabled'] = True
    original = copy.deepcopy(editor.doc)
    resolved = W.expand_layout(editor.doc, 99, root)
    colour = W.expand('__colour__', 99, root)
    check('region prompts expand with the main prompt selection',
          resolved['items'][0]['caption'] == 'A ' + colour + ' cube beside a __missing__ object')
    check('repeated region wildcards share the selection', resolved['items'][1]['caption'] == colour + ' lettering')
    check('exact wording stays literal', resolved['items'][1]['text'] == '__colour__')
    check('editable layout is not mutated', editor.doc == original)
    check('layout geometry is unchanged', resolved['items'][0]['box'] == region['box'])
    check('layout selection is deterministic', resolved == W.expand_layout(editor.doc, 99, root))
    check('different job seeds can produce different region prompts',
          len({W.expand_layout(editor.doc, seed, root)['items'][0]['caption'] for seed in range(20)}) == 2)
    editor.doc['enabled'] = False
    check('disabled layouts remain literal', W.expand_layout(editor.doc, 99, root) == editor.doc)

    # This fixed seed and broad palette expose reused occurrence counters.
    # Exercise the actual job path, including continuation into regions.
    from submission import build_job, build_batch, Submission
    class Registry:
        def family_of(self, entry): return {}
        def build(self, entry, params, object_info=None):
            return {'params': copy.deepcopy(params)}
    rows = [dict(text=str(i), enabled=True) for i in range(1000)]
    params = dict(seed=42, positive='__number__ __number__', negative='__number__',
                  moss_layout=dict(enabled=True, items=[
                      dict(caption='__number__', text='__number__'),
                      dict(caption='__number__', enabled=False),
                      dict(caption='__number__')]),
                  wildcard_options={'number': rows}, wildcard_independent=True)
    independent = build_job(Registry(), None, params)['params']
    picks = independent['positive'].split() + independent['negative'].split()
    # Metadata retains raw region captions; inspect conditioning through a stub.
    class CaptureRegistry(Registry):
        def build(self, entry, params, object_info=None):
            result = super().build(entry, params, object_info)
            result['conditioning'] = copy.deepcopy(params)
            return result
    job = build_job(CaptureRegistry(), None, params)
    regions = job['conditioning']['moss_layout']['items']
    picks += [regions[0]['caption'], regions[2]['caption']]
    check('each occurrence draws independently across boxes and regions', len(set(picks)) == 5)
    check('independent jobs reproduce exactly', job == build_job(CaptureRegistry(), None, params))
    check('literal text and disabled region captions stay untouched',
          regions[0]['text'] == '__number__' and regions[1]['caption'] == '__number__')
    check('independent metadata retains mode and original prompts',
          independent['wildcard_independent'] is True and
          independent['prompt_boxes']['positive'] == params['positive'] and
          independent['moss_layout'] == params['moss_layout'])
    linked = build_job(CaptureRegistry(), None, dict(params, wildcard_independent=False))
    old = W.expand('__number__', 42, options=params['wildcard_options'])
    check('disabled mode preserves the original seed mapping',
          linked['params']['positive'] == old + ' ' + old and
          linked['params']['negative'] == old and
          linked['conditioning']['moss_layout']['items'][2]['caption'] == old)
    frozen = Submission.freeze(params, None, CaptureRegistry(), None, 2, [], -1)
    params['wildcard_independent'] = False
    batch = build_batch(frozen)
    check('queued mode stays frozen and each batch seed changes the draws',
          all(j['params']['wildcard_independent'] for j in batch) and
          batch[0]['params']['positive'] != batch[1]['params']['positive'])
    only_one = {'colour': [dict(text='blue', enabled=True), dict(text='red', enabled=False)]}
    check('independent draws respect disabled choices and allow chance repeats',
          W.expand('__colour__ __colour__', 42, options=only_one, independent=True) == 'blue blue')

    state_path = root / 'settings.json'
    options = W.load_options(state_path, root)
    options['colour'][0]['enabled'] = False
    W.save_options(state_path, options)
    check('line choices persist across sessions', W.load_options(state_path, root) == options)
    check('disabled lines never selected', all(W.expand('__colour__', seed, root, options) == 'blue' for seed in range(30)))
    check('same filtered choice in both boxes', W.expand_prompts('__colour__', '__colour__', 1, root, options) == ('blue', 'blue'))
    (root / 'colour.txt').write_text('blue\nred\ngreen\n', encoding='utf-8')
    check('choices follow lines through file reorder and new lines default on',
          W.load_options(state_path, root)['colour'] == [dict(text='blue', enabled=True), dict(text='red', enabled=False), dict(text='green', enabled=True)])
    check('metadata snapshot remains reproducible after wildcard file changes', W.expand('__colour__', 1, root, options) == 'blue')
    options['colour'][1]['enabled'] = False
    try:
        W.expand('__colour__', 1, root, options)
        raise AssertionError('all-disabled wildcard was accepted')
    except ValueError as error:
        check('all-disabled referenced wildcard gives actionable error', 'no enabled lines' in str(error))

print("wildcards: all checks passed")
