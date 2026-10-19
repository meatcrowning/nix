"""Saved-output controls, independent of the live generation state."""

LABELS = {
    'model': 'Model', 'positive': 'Prompt', 'negative': 'Negative prompt',
    'aspectW': 'AR width', 'aspectH': 'AR height', 'megapixels': 'MP',
    'seed': 'Seed number', 'width': 'Width', 'height': 'Height',
    'steps': 'Steps', 'cfg': 'Guidance', 'sampler_name': 'Sampler',
    'scheduler': 'Schedule', 'denoise': 'Denoise', 'batch_size': 'Batch size',
    'duration': 'Seconds', 'fps': 'Frames per second', 'system_prompt': 'System prompt',
    'shift_start': 'Starting shift', 'shift_end': 'Ending shift',
    'start_percent': 'Start fraction', 'end_percent': 'End fraction',
    'multiplier': 'Multiplier', 'curve': 'Curve', 'outside_window': 'Outside interval',
    'negpip': 'Negative prompt weighting', 'model_sampling': 'Model sampling patch',
    'caption': 'Prompt', 'text': 'Exact wording', 'tags': 'Tags', 'palette': 'Palette',
    'krea_sampling': 'Krea sampling', 'krea_shift': 'Krea shift',
    'reference_megapixels': 'Reference budget (MP)', 'meta': 'Medium / genre tags',
}
ORDER = ('model', 'positive', 'negative', 'seed', 'aspectW', 'aspectH', 'megapixels', 'width', 'height', 'steps', 'cfg',
         'sampler_name', 'scheduler', 'denoise', 'batch_size', 'duration', 'fps',
         'system_prompt', 'krea_sampling', 'krea_shift', 'reference_megapixels')


def fields(params):
    """Show only recorded values; never fill gaps with today's defaults."""
    if not params:
        return []
    data = dict(params)
    data.update({k: v for k, v in (data.pop('prompt_boxes', {}) or {}).items()
                 if k in ('positive', 'negative')})
    if data.get('width', 0) > 0 and data.get('height', 0) > 0:
        import math
        width, height = int(data['width']), int(data['height'])
        data.setdefault('aspectW', width // math.gcd(width, height))
        data.setdefault('aspectH', height // math.gcd(width, height))
        data.setdefault('megapixels', width * height / 1000000.0)
    result = []

    def add(key, value, title=None):
        if value is None:
            return
        name = title or LABELS.get(key, key.replace('_', ' ').capitalize())
        if isinstance(value, dict):
            result.append(dict(kind='heading', label=name, value='', text=''))
            for child in sorted(value):
                add(child, value[child])
            return
        if isinstance(value, list):
            if all(isinstance(v, (str, type(u''))) for v in value):
                value = ', '.join(value)
            else:
                for index, item in enumerate(value):
                    add(key, item, '%s %d' % (name, index + 1))
                return
        kind = ('choice' if key in ('model', 'sampler_name', 'scheduler', 'curve', 'outside_window', 'krea_sampling', 'kind') else
                'check' if isinstance(value, bool) else
                'number' if isinstance(value, (int, float)) and key != 'seed' and abs(value) <= 2**53 else
                'prompt' if key in ('positive', 'negative', 'caption', 'text', 'system_prompt') else 'entry')
        text = str(value) if not isinstance(value, (str, type(u''))) else value
        result.append(dict(key=key, label=name, value=value if kind in ('number', 'check') else text, text=text, kind=kind))

    for key in ORDER:
        if key in data:
            add(key, data.pop(key))
    layout = data.pop('moss_layout', None)
    for key in sorted(data):
        add(key, data[key])
    if layout:
        add('summary', layout.get('summary', {}), 'Scene')
        for index, region in enumerate(layout.get('items', [])):
            result.append(dict(kind='heading', label='Region %d' % (index + 1), value='', text=''))
            for key in ('kind', 'caption', 'text', 'tags', 'palette', 'box', 'typography', 'enabled', 'locked'):
                if key in region:
                    value = region[key]
                    if key == 'box':
                        value = ', '.join(str(v) for v in value)
                    add(key, value)
    return result
