"""Relative spatial rankings from saved maps, excluding English function words."""
import math
import re

# Use full words in the saved prompt so subword pieces of content words survive.
# This is a lexical heuristic, not a claim that these tokens have no model effect.
STOP_WORDS = frozenset('''a an the and or but nor so yet as at by for from in into of on onto to with
is am are was were be been being do does did have has had having can could will would shall should may might must
he her hers herself him his himself i me my mine myself we us our ours ourselves
she they them their theirs themselves it its itself you your yours yourself yourselves
this that these those which who whom whose what there here then than also just very'''.split())
WORD = re.compile(r"\w+(?:['’-]\w+)*", re.UNICODE)


def content_tokens(document):
    words = [(m.start(), m.end(), m.group().casefold()) for m in WORD.finditer(document.get('prompt', ''))]
    result = []
    for token in document['tokens']:
        if not token['visible'] or not WORD.search(token['text']):
            continue
        start, end = token.get('start', -1), token.get('end', -1)
        matched = [word for a, b, word in words if a < end and b > start] if start >= 0 else []
        if not matched:
            matched = [m.group().casefold() for m in WORD.finditer(token['text'])]
        if any(word not in STOP_WORDS for word in matched):
            display = token['text'].strip().replace('\n', '↵')
            if len(matched) == 1 and display.casefold() != matched[0]:
                display = '%s [%s]' % (matched[0], display)
            result.append(dict(token, display=display))
    return result


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
    return dict(areas=hot, focused=focused[:4])
