"""Relative spatial rankings from saved maps, excluding English function words."""
import math
import re
import json
import unicodedata
from difflib import SequenceMatcher

# Use full words in the saved prompt so subword pieces of content words survive.
# This is a lexical heuristic, not a claim that these tokens have no model effect.
STOP_WORDS = frozenset('''a an the and or but nor so yet as at by for from in into of on onto to with
is am are was were be been being do does did have has had having can could will would shall should may might must
he her hers herself him his himself i me my mine myself we us our ours ourselves
she they them their theirs themselves it its itself you your yours yourself yourselves
this that these those which who whom whose what there here then than also just very'''.split())
WORD = re.compile(r"\w+(?:['’-]\w+)*", re.UNICODE)


def word_maps(document, pixels):
    """Average saved planes per word occurrence; retain source token identities."""
    prompt = document.get('prompt', '')
    words = list(WORD.finditer(prompt))
    visible = [t for t in document['tokens'] if t['visible']]
    area = document['width'] * document['height']
    groups, lookup, planes = {}, {}, bytearray()
    for token in visible:
        start, end = token.get('start', -1), token.get('end', -1)
        spans = [m for m in words if start >= 0 and m.start() < end and m.end() > start]
        if spans:
            start, end = spans[0].start(), spans[-1].end()
            key = (start, end)
            pieces = [t for t in visible if t.get('start', -1) < end and t.get('end', -1) > start]
            text = prompt[start:end]
        else:
            # Punctuation and legacy maps without offsets remain individually selectable.
            key, pieces, text = ('token', token['index']), [token], token['text'].strip()
        if key not in groups:
            index = len(groups)
            groups[key] = dict(index=index, text=text, start=start, end=end, visible=True,
                               pieces=[t['text'].strip() for t in pieces],
                               source_indices=[t['index'] for t in pieces])
            planes.extend(round(sum(pixels[t['index']*area+i] for t in pieces)/len(pieces))
                          for i in range(area))
        lookup[token['index']] = groups[key]
    return (dict(document, tokens=list(groups.values())), bytes(planes)), lookup


def word_label(token):
    pieces = token['pieces']
    return '%s - %s: %s' % (token['text'], 'token' if len(pieces) == 1 else 'tokens',
                            ', '.join('[%s]' % piece.replace('\n', '↵') for piece in pieces))


def descriptive_spans(prompt):
    """Keep layout prose values, never JSON keys, region types or coordinates."""
    try:
        layout = json.loads(prompt)
    except (ValueError, TypeError):
        return [(0, len(prompt))]
    if not (isinstance(layout, dict) and isinstance(layout.get('summary'), dict)
            and isinstance(layout.get('items'), list)):
        return [(0, len(prompt))]
    from moss_data import json_value_span
    spans = []
    def collect(value, path):
        if isinstance(value, str):
            start, end = json_value_span(prompt, path)
            spans.append((start+1, end-1))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                collect(item, path+(i,))
    for key in ('caption', 'meta', 'palette'):
        if key in layout['summary']:
            collect(layout['summary'][key], ('summary', key))
    for i, item in enumerate(layout['items']):
        if isinstance(item, dict):
            for key in ('caption', 'text', 'tags', 'palette'):
                if key in item:
                    collect(item[key], ('items', i, key))
    return spans


def content_tokens(document):
    prompt = document.get('prompt', '')
    spans = descriptive_spans(prompt)
    layout = spans != [(0, len(prompt))]
    words = [(m.start(), m.end(), m.group().casefold()) for m in WORD.finditer(prompt)
             if any(a < m.end() and b > m.start() for a, b in spans)]
    result = []
    for token in document['tokens']:
        if not token['visible'] or not WORD.search(token['text']):
            continue
        start, end = token.get('start', -1), token.get('end', -1)
        if layout and not any(a < end and b > start for a, b in spans):
            continue
        matched = [word for a, b, word in words if a < end and b > start] if start >= 0 else []
        if not matched:
            matched = [m.group().casefold() for m in WORD.finditer(token['text'])]
        if any(word not in STOP_WORDS for word in matched):
            display = token['text'].strip().replace('\n', '↵')
            if len(matched) == 1 and display.casefold() != matched[0]:
                display = '%s [%s]' % (matched[0], display)
            identity = ' '.join(word for word in matched if word not in STOP_WORDS)
            result.append(dict(token, display=display, identity=identity))
    return result


def duplicate_token(token, selected):
    """Collapse repeated words/subpieces and conservative spelling variants."""
    def key(item):
        word = unicodedata.normalize('NFKC', item.get('identity', item['text'])).casefold()
        word = ''.join(c for c in word if c.isalnum())
        if word.endswith('ies') and len(word) > 4:
            word = word[:-3] + 'y'
        elif word.endswith('s') and not word.endswith(('ss', 'us', 'is')) and len(word) > 3:
            word = word[:-1]
        return word
    word = key(token)
    for other in selected:
        previous = key(other['token'])
        if word == previous or (min(len(word), len(previous)) >= 5 and
                                SequenceMatcher(None, word, previous).ratio() >= .88):
            return True
    return False


def rank(document, pixels):
    """Return separated hot neighborhoods and up to four compact token maps."""
    w, h = document['width'], document['height']
    area = w * h
    tokens = content_tokens(document)
    planes = [pixels[t['index'] * area:(t['index'] + 1) * area] for t in tokens]
    if not tokens:
        return dict(areas=[], focused=[])
    mean = [sum(p[i] for p in planes) / (255 * len(planes)) for i in range(area)]
    radius = min(3, (min(w, h) - 1) // 2)
    side = radius * 2 + 1
    candidates = []
    for y in range(radius, h - radius):
        for x in range(radius, w - radius):
            cells = [j*w+i for j in range(y-radius, y+radius+1) for i in range(x-radius, x+radius+1)]
            score = sum(mean[i] for i in cells) / len(cells)
            if score > 0:
                candidates.append((score, x, y, cells))
    hot = []
    separation = max(side, min(12, min(w, h) / 5))
    for score, x, y, cells in sorted(candidates, reverse=True):
        if any(math.hypot(x-a['x'], y-a['y']) < separation for a in hot):
            continue
        best = max(range(len(tokens)), key=lambda k: sum(planes[k][i] for i in cells))
        # Skip the neighborhood rather than mislabel it with a weaker runner-up.
        if duplicate_token(tokens[best], hot):
            continue
        hot.append(dict(score=score, x=x, y=y, side=side, token=dict(tokens[best]),
                        association=sum(planes[best][i] for i in cells) / (255*len(cells))))
        if len(hot) == 4:
            break
    focused = []
    for token, plane in zip(tokens, planes):
        weights = [max(0, v/255 - .7)**2 for v in plane]
        total = sum(weights)
        if not total:
            continue
        x = sum(v*(i % w) for i, v in enumerate(weights)) / total
        y = sum(v*(i // w) for i, v in enumerate(weights)) / total
        spread = math.sqrt(sum(v*((i % w-x)**2 + (i // w-y)**2) for i, v in enumerate(weights)) / total)
        focused.append(dict(radius=spread, x=x, y=y, token=dict(token)))
    focused.sort(key=lambda item: (item['radius'], item['token']['index']))
    unique = []
    for item in focused:
        if not duplicate_token(item['token'], unique):
            unique.append(item)
            if len(unique) == 4:
                break
    return dict(areas=hot, focused=unique)
