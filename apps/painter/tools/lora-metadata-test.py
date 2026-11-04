#!/usr/bin/env python3
"""LoRA graph recovery and snapshot validation; synthetic data, no backend."""
from pathlib import Path
import sys
import json

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP), str(APP.parent / 'pylib')]
import outmeta
import userprefs


def node(cls, **inputs):
    return dict(class_type=cls, inputs=inputs)


def main():
    # Deliberately unordered, with an unrelated LoRA that must not be injected.
    graph = {
        'unused': node('LoraLoaderModelOnly', model=['base', 0], lora_name='unused', strength_model=1),
        'sampler': node('PainterMossSampler', model=['guidance', 0], positive=['positive', 0], cfg=3),
        'second': node('LoraLoader', model=['first', 0], clip=['clip', 0],
                       lora_name='b', strength_model=-.6, strength_clip=.2),
        'base': node('UNETLoader', unet_name='moss.safetensors'),
        'first': node('LoraLoaderModelOnly', model=['correction', 0], lora_name='a', strength_model=0),
        'guidance': node('SkipLayerGuidanceDiTSimple', model=['second', 0]),
        'correction': dict(node('LoraLoaderModelOnly', model=['base', 0],
                               lora_name='destripe', strength_model=1.5),
                           _meta={'painter_role': 'moss_destripe'}),
        'positive': node('CLIPTextEncode', text='a bird'),
    }
    expected = [dict(name='a', strength=0., patches_clip=False),
                dict(name='b', strength=-.6, patches_clip=True, strength_clip=.2)]
    p = outmeta.params_from_graph(graph)
    assert p['loras'] == expected and p['positive'] == 'a bird'
    assert p['moss_destripe_strength'] == 1.5 and p['moss_destripe_lora'] == 'destripe'
    legacy = outmeta._saved_params(json.dumps({'positive': 'old tag'}), graph)
    assert legacy['loras'] == expected
    explicit = outmeta._saved_params(json.dumps({'loras': []}), graph)
    assert explicit['loras'] == []
    fix = outmeta._moss_correction()
    graph['base']['inputs']['unet_name'] = fix['models'][0]
    graph['correction']['inputs']['lora_name'] = fix['file']
    graph['correction'].pop('_meta')
    assert outmeta.params_from_graph(graph)['loras'] == expected
    for cls in ('KSampler', 'SamplerCustom', 'SamplerCustomAdvanced'):
        graph['sampler']['class_type'] = cls
        assert outmeta.params_from_graph(graph)['loras'] == expected
    graph['sampler'] = node('SamplerCustomAdvanced', guider=['guider', 0])
    graph['guider'] = node('CFGGuider', model=['guidance', 0])
    assert outmeta.params_from_graph(graph)['loras'] == expected
    graph['guider']['inputs']['model'] = ['base', 0]
    assert outmeta.params_from_graph(graph)['loras'] == []
    # A corrupt graph cycle must terminate.
    graph['guider']['inputs']['model'] = ['guider', 0]
    assert outmeta.params_from_graph(graph)['loras'] == []
    choices = [dict(name='a', ok=True, patches_clip=True), dict(name='b', ok=False)]
    clean = userprefs.normalize_loras([dict(name='a', strength=0, enabled=False),
        dict(name='a', strength=9), dict(name='b'), None, dict(name='missing')], choices)
    assert clean == [dict(name='a', strength=0, enabled=False, patches_clip=True)]
    for strength in ('bad', None, float('nan'), float('inf')):
        assert userprefs.normalize_loras([dict(name='a', strength=strength)], choices) == []
    assert userprefs.normalize_loras({'name': 'a'}, choices) == []
    assert userprefs.normalize_loras([dict(name='a', patchesClip=False)], choices)[0]['patches_clip'] is False
    print('PASS LoRA chain order, MOSS correction, sampler routes, malformed metadata and snapshots')


if __name__ == '__main__':
    main()
