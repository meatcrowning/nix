"""History query parsing and searchable metadata; no GUI or filesystem access."""
from __future__ import unicode_literals

from datetime import datetime
import re
import unicodedata

HELP = ('All terms must match. Use "quoted phrases" and -excluded terms.\n'
        'Fields: filename:, positive: (or prompt:), negative:, model:, family:, '
        'lora:, seed:, type:image or type:video.\n'
        'Dates use file modification time: date:YYYY-MM-DD, before:YYYY-MM-DD, '
        'after:YYYY-MM-DD (before/after are exclusive).\n'
        'Plain searches omit negative prompts. Example: model:moss "red bird" -lora:sketch')
FIELDS = {'filename', 'positive', 'prompt', 'negative', 'model', 'family',
          'lora', 'seed', 'type', 'date', 'before', 'after'}


def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', str('' if value is None else value)).casefold().split())


def parse(text):
    """Tolerate unfinished quotes while typing; unknown fields stay literal."""
    terms = []
    for raw in re.findall(r'(?:[^\s"]+|"[^"]*(?:"|$))+', text):
        excluded = raw.startswith('-') and len(raw) > 1
        if excluded:
            raw = raw[1:]
        field, sep, value = raw.partition(':')
        field = field.casefold()
        if not sep or field not in FIELDS:
            field, value = '', raw
        value = normalize(value.replace('"', ''))
        if value:
            terms.append((field, value, excluded))
    return terms


def document(name, params=None, video=False, mtime=0):
    p = params if isinstance(params, dict) else {}
    boxes = p.get('prompt_boxes')
    boxes = boxes if isinstance(boxes, dict) else {}
    doc = {key: normalize(p.get(key)) for key in ('model', 'family', 'seed')}
    doc.update(filename=normalize(name), type='video' if video else 'image')
    for key in ('positive', 'negative'):
        # Saved editor boxes separate NegPiP's folded negative from its positive.
        doc[key] = normalize(boxes.get(key, p.get(key, '')))
    toggles = p.get('toggles')
    if not (isinstance(toggles, dict) and toggles.get('negpip') and boxes):
        expanded = normalize(p.get('positive'))
        if expanded and expanded != doc['positive']:
            doc['positive'] = normalize(doc['positive'] + ' ' + expanded)
    doc['prompt'] = doc['positive']
    loras = p.get('loras')
    doc['lora'] = normalize(' '.join(str(r.get('name', '')) for r in loras
                                    if isinstance(r, dict))) if isinstance(loras, list) else ''
    try:
        doc['date'] = datetime.fromtimestamp(mtime).date().isoformat() if mtime else ''
    except (ValueError, TypeError, OverflowError, OSError):
        doc['date'] = ''
    doc[''] = ' '.join(doc[k] for k in ('filename', 'positive', 'model', 'family', 'lora'))
    return doc


def matches(doc, terms):
    for field, value, excluded in terms:
        if field in ('date', 'before', 'after'):
            try:
                valid = datetime.strptime(value, '%Y-%m-%d').date().isoformat() == value
            except ValueError:
                valid = False
            date = doc.get('date', '')
            hit = bool(valid and date and (date < value if field == 'before' else
                       date > value if field == 'after' else date == value))
        elif field in ('seed', 'type'):
            hit = value == doc.get(field, '')
        else:
            hit = value in doc.get(field, '')
        if hit == excluded:
            return False
    return True
