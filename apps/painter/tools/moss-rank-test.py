#!/usr/bin/env python3
"""Pure CPU checks for lexical exclusions and spatial rankings."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import moss_rank

prompt = 'with leather and 4'
tokens = [dict(index=i, text=text, start=a, end=b, visible=True) for i, (text, a, b) in enumerate([
    ('w', 0, 1), ('ith', 1, 4), (' leat', 4, 9), ('her', 9, 12), (' and', 12, 16), (' 4', 16, 18), ('",', 18, 20)])]
assert [t['index'] for t in moss_rank.content_tokens(dict(prompt=prompt, tokens=tokens))] == [2, 3, 5]
assert moss_rank.content_tokens(dict(prompt=prompt, tokens=tokens))[1]['display'] == 'leather [her]'
# The excluded function word has the strongest map. It must not win an area.
doc = dict(width=16, height=16, prompt='with bolt metal', tokens=[
    dict(index=0, text='with', start=0, end=4, visible=True),
    dict(index=1, text='bolt', start=5, end=9, visible=True),
    dict(index=2, text='metal', start=10, end=15, visible=True)])
compact = bytearray(256)
compact[8*16+8] = 255
pixels = bytes([255]*256) + compact + bytes([200]*256)
ranks = moss_rank.rank(doc, pixels)
assert ranks['areas'] and all(a['token']['text'] == 'metal' for a in ranks['areas'])
assert [f['token']['text'] for f in ranks['focused']] == ['bolt', 'metal']
assert ranks['focused'][0]['radius'] == 0 < ranks['focused'][1]['radius']
assert len(ranks['areas']) <= 4
assert moss_rank.rank(dict(doc, tokens=doc['tokens'][:1]), pixels) == dict(areas=[], focused=[])
assert moss_rank.rank(doc, bytes(768)) == dict(areas=[], focused=[])
print('PASS lexical filtering, content subpieces, spatial ranking, area labels and empty maps')
