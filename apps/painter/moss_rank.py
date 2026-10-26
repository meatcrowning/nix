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


def word_groups(document):
    """Resolve word occurrences once, without reading any spatial planes."""
    prompt = document.get('prompt', '')
    words = list(WORD.finditer(prompt))
    visible = [t for t in document['tokens'] if t['visible']]
    groups, lookup = {}, {}
    for token in visible:
        start, end = token.get('start', -1), token.get('end', -1)
        spans = [m for m in words if start >= 0 and m.start() < end and m.end() > start]
        if spans:
            start, end = spans[0].start(), spans[-1].end()
            key = (start, end)
            pieces = [t for t in visible if t.get('start', -1) < end and t.get('end', -1) > start]
            text = prompt[start:end]
        else:
            key, pieces, text = ('token', token['index']), [token], token['text'].strip()
        if key not in groups:
            groups[key] = dict(index=len(groups), text=text, start=start, end=end, visible=True,
                               pieces=[t['text'].strip() for t in pieces],
                               source_indices=[t['index'] for t in pieces])
        lookup[token['index']] = groups[key]
    return list(groups.values()), lookup


def word_maps(document, pixels):
    """Use raw-grouped saved word maps when available; cache legacy grouping."""
    if '_words' in document and document.get('_words_source') is pixels:
        return document['_words']
    groups, lookup = word_groups(document)
    area = document['width'] * document['height']
    if document.get('words') == groups and '_word_pixels' in document:
        planes = document['_word_pixels']
    else:
        planes = bytearray()
        for group in groups:
            parts = [pixels[i*area:(i+1)*area] for i in group['source_indices']]
            planes.extend(parts[0] if len(parts) == 1 else
                          bytes(round(sum(values)/len(parts)) for values in zip(*parts)))
        planes = bytes(planes)
    doc = {k:v for k,v in document.items() if not k.startswith('_') and k != 'words'}
    doc['tokens'] = groups
    result = ((doc, planes), lookup)
    document['_words'] = result
    document['_words_source'] = pixels
    return result


def neighborhood(width, height, radius=3):
    """A fixed fraction of each map axis, referenced to the original 64 grid."""
    return (min((width-1)//2, max(1, round(radius*width/64))),
            min((height-1)//2, max(1, round(radius*height/64))))


def summed_area(plane, width, height):
    table = [0] * ((width+1)*(height+1))
    for y in range(height):
        row = 0
        for x in range(width):
            row += plane[y*width+x]
            table[(y+1)*(width+1)+x+1] = row + table[y*(width+1)+x+1]
    return table


def area_sum(table, width, x0, y0, x1, y1):
    stride = width+1
    return table[y1*stride+x1]-table[y0*stride+x1]-table[y1*stride+x0]+table[y0*stride+x0]


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


def rank(document, pixels, limit=4, image_size=None, extremes=False):
    """Return unique spatial rankings; None keeps all entries for fitted headers."""
    cache = document.setdefault('_rankings', {})
    key = (limit, tuple(image_size) if image_size else None, extremes)
    if key in cache and cache[key][0] is pixels:
        return cache[key][1]
    w, h = document['width'], document['height']
    area = w * h
    tokens = content_tokens(document)
    planes = [pixels[t['index'] * area:(t['index'] + 1) * area] for t in tokens]
    if not tokens:
        return dict(areas=[], focused=[], area_headers=[], focus_headers=[]) if extremes else dict(areas=[], focused=[])
    mean = [sum(p[i] for p in planes) / (255 * len(planes)) for i in range(area)]
    rx, ry = neighborhood(w, h)
    sx, sy = 2*rx+1, 2*ry+1
    table = summed_area(mean, w, h)
    candidates = []
    for y in range(ry, h-ry):
        for x in range(rx, w-rx):
            score = area_sum(table,w,x-rx,y-ry,x+rx+1,y+ry+1)/(sx*sy)
            if score > 0 or extremes:
                candidates.append((score,x,y))
    winners = [0] * area
    winner_scores = [-1] * area
    for k, plane in enumerate(planes):
        local = summed_area(plane, w, h)
        for _, x, y in candidates:
            value = area_sum(local,w,x-rx,y-ry,x+rx+1,y+ry+1)
            index = y*w+x
            if value > winner_scores[index]:
                winner_scores[index], winners[index] = value, k
    hot = []
    separation = max(sx/w, sy/h, 12/64)
    for score,x,y in sorted(candidates, reverse=True):
        if any(math.hypot((x-a['x'])/w,(y-a['y'])/h) < separation for a in hot):
            continue
        best = winners[y*w+x]
        if duplicate_token(tokens[best], hot):
            continue
        association = winner_scores[y*w+x]/(255*sx*sy)
        hot.append(dict(score=score,x=x,y=y,side=sx,side_y=sy,token=dict(tokens[best]),
                        association=association,percentage=association*100))
        if limit is not None and len(hot) == limit:
            break
    image_w, image_h = image_size or (w, h)
    scale_x, scale_y = image_w/w, image_h/h
    focused = []
    for token, plane in zip(tokens, planes):
        weights = [max(0, v/255 - .7)**2 for v in plane]
        total = sum(weights)
        if not total:
            continue
        x = sum(v*(i % w) for i, v in enumerate(weights)) / total
        y = sum(v*(i // w) for i, v in enumerate(weights)) / total
        spread = math.sqrt(sum(v*(((i % w-x)*scale_x)**2 + ((i // w-y)*scale_y)**2) for i, v in enumerate(weights)) / total)
        focused.append(dict(radius=spread, x=x, y=y, token=dict(token),
                            percentage=spread/math.hypot(image_w, image_h)*100))
    focused.sort(key=lambda item: (item['radius'], item['token']['index']))
    unique = []
    for item in focused:
        if not duplicate_token(item['token'], unique):
            unique.append(item)
            if limit is not None and len(unique) == limit:
                break
    if extremes:
        areas = [dict(item, extreme='hot') for item in hot[:6]]
        for score, x, y in sorted(candidates):
            if any(math.hypot((x-a['x'])/w, (y-a['y'])/h) < separation for a in areas):
                continue
            best = winners[y*w+x]
            if duplicate_token(tokens[best], areas):
                continue
            areas.append(dict(score=score, x=x, y=y, side=sx, side_y=sy,
                              token=dict(tokens[best]), extreme='cold',
                              association=winner_scores[y*w+x]/(255*sx*sy), percentage=score*100))
            if sum(a['extreme'] == 'cold' for a in areas) == 3:
                break
        spread = [dict(item, extreme='most') for item in unique[:6]]
        for item in sorted(focused, key=lambda item: (-item['radius'], item['token']['index'])):
            if not duplicate_token(item['token'], spread):
                spread.append(dict(item, extreme='least'))
            if sum(a['extreme'] == 'least' for a in spread) == 3:
                break
        result = dict(areas=areas, focused=spread,
                      area_headers=unique_entries(hot, areas),
                      focus_headers=unique_entries(unique, spread))
    else:
        result = dict(areas=hot, focused=unique)
    cache[key] = (pixels, result)
    return result


def unique_entries(entries, exclude=()):
    selected, result = list(exclude), []
    for entry in entries:
        if not duplicate_token(entry['token'], selected):
            result.append(entry)
            selected.append(entry)
    return result


def association_lists(document, pixels, selected, aggregate):
    """Rank eligible words by combined-map strength and selected-map correlation."""
    area = document['width'] * document['height']
    tokens = content_tokens(document)
    planes = {t['index']: pixels[t['index']*area:(t['index']+1)*area] for t in tokens}
    weight = sum(aggregate)
    all_tokens = [dict(token=t, percentage=sum(a*b for a, b in zip(planes[t['index']], aggregate)) /
                       (255*weight)*100 if weight else 0) for t in tokens]
    all_tokens.sort(key=lambda item: (-item['percentage'], item['token']['index']))
    stats = {i: (sum(p), sum(v*v for v in p)) for i,p in planes.items()}
    related = []
    for choice in selected:
        plane = pixels[choice['index']*area:(choice['index']+1)*area]
        total, squares = sum(plane), sum(v*v for v in plane)
        variance = max(0, squares-total*total/area)
        entries = []
        for token in tokens:
            candidate = planes[token['index']]
            other_total, other_squares = stats[token['index']]
            denominator = math.sqrt(variance*max(0, other_squares-other_total*other_total/area))
            score = (sum(a*b for a,b in zip(plane,candidate))-total*other_total/area)/denominator if denominator else 0
            if score > 0:
                entries.append(dict(token=token, percentage=min(100, score*100)))
        entries.sort(key=lambda item: (-item['percentage'], item['token']['index']))
        related.append(unique_entries(entries, [dict(token=choice)]))
    return unique_entries(all_tokens), related
