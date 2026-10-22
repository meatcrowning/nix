"""Project saved metadata into an independent normal parameter-panel state."""
import copy
from dimensions import controls_for_size

BASE = dict(moss_layout={}, positive='', negative='', aspectW=1, aspectH=1, width=1024, height=1024, steps=20, cfg=7.0,
            denoise=1.0, sampler_name='euler', scheduler='normal', seed=-1,
            randomSeed=True, reuseSeed=False, count=1, batch_size=1,
            duration=5.0, fps=24.0, megapixels=1.0, still=False,
            editNoScale=True, editMegapixels=1.0, useInputImage=False,
            useLastFrame=False, negpip=False, modelSampling=False,
            ms=dict(shift_start=3.5, shift_end=1.2, start_percent=0.0, end_percent=.5,
                    curve='ease_in', outside_window='hold', multiplier=1.0),
            system_prompt='', krea_sampling='native', krea_shift=1.0,
            reference_megapixels=1.0, useReferences=False)


def snapshot(params, ctl):
    if not params:
        return None
    from moss_layout import import_prompt
    p = import_prompt(params)
    name = p.get('model', '')
    index = ctl.models.index_of_name(name)
    entry = ctl.models.entry_at(index) if index >= 0 else None
    family = (ctl.reg.family_of(entry) or {}) if entry and ctl.reg else {}
    # Layout-bearing outputs remain inspectable even when their model is absent.
    moss = family.get('id') == 'moss_image' or bool(p.get('moss_layout'))
    defaults = ctl.reg.defaults_for(entry) if entry and ctl.reg else {}
    g = copy.deepcopy(BASE)
    g.update({k: v for k, v in defaults.items() if k in g})
    g.update({k: v for k, v in p.items() if k in g})
    g.update({k: v for k, v in (p.get('prompt_boxes') or {}).items() if k in ('positive', 'negative')})
    if p.get('width', 0) > 0 and p.get('height', 0) > 0:
        g.update(controls_for_size(p['width'], p['height'],
                                   (family.get('resolution') or {}).get('multiple', 16), p))
    g.update(randomSeed=False, reuseSeed=False, still=p.get('kind') == 'still')
    toggles = p.get('toggles') or {}
    g.update(negpip=bool(toggles.get('negpip', g['negpip'])),
             modelSampling=bool(toggles.get('model_sampling', g['modelSampling'])))
    if p.get('model_sampling'):
        g['ms'] = dict(g['ms'], **p['model_sampling'])
    g.update(useInputImage=bool(p.get('use_input_image')), useLastFrame=bool(p.get('use_last_frame')),
             useReferences=bool(p.get('reference_images_local')),
             promptTransform=family.get('prompt_transform', 'none'),
             multiple=int((family.get('resolution') or {}).get('multiple', 16)))
    edit = bool(p.get('edit') or p.get('kind') == 'edit')
    flags = dict(layoutSupport=moss, isVideo=family.get('kind') == 'video' or p.get('kind') in ('video', 'still'),
                 isEdit=edit, nativeScheduler=family.get('native_scheduler', ''),
                 supportsPatches=family.get('supports_patches', not moss),
                 supportsLoras=family.get('supports_loras', not moss))
    for target, source in [('encoderControls', 'encoder_controls'), ('referenceImages', 'reference_images'),
                           ('optionalEditImage', 'optional_edit_image'), ('fixedSampling', 'fixed_sampling'),
                           ('tagCompletion', 'tag_completion')]:
        flags[target] = bool(family.get(source))
    for target, source in [('editSampling', 'sampling_controls'), ('editPatches', 'patch_controls'),
                           ('editSharedImageSize', 'shared_image_size')]:
        flags[target] = bool((family.get('edit') or {}).get(source))
    flags['editMultipleImages'] = (family.get('edit') or {}).get('max_images') != 1
    models = [{k: v for k, v in row.items() if k != 'entry'} for row in ctl.models._rows]
    if index < 0:
        models.append(dict(name=name or 'Unrecorded model', known=False, problem='Model unavailable',
                           family='', label='', quant='', pairing='', overridden=False, path='', size=0))
        index = len(models) - 1
    loras = [dict(dict(enabled=True, patches_clip=False, strength=1.0), **row) for row in p.get('loras') or []]
    return dict(encoder=p.get('encoder', ''), vae=p.get('vae', ''),
                separatePairing=bool(family) and family.get('loader_shape') != 'checkpoint',
                model=name or 'Unrecorded model', selectedIndex=index, models=models,
                mode='edit' if edit else '', modes=ctl.modes(), settings=g, flags=flags,
                revision=0, samplers=list(ctl.samplers), schedulers=list(ctl.schedulers),
                curves=list(ctl.curves), outsideWindows=list(ctl.outsideWindows),
                input=p.get('input_image_local') or next(iter(p.get('reference_images_local') or []), ''), last=p.get('last_image_local', ''),
                references=(p.get('reference_images_local') or [])[1:], loras=loras,
                choices=[dict(name=r['name'], ok=True, reason='Saved LoRA', patches_clip=r.get('patches_clip', False), score=0)
                         for r in loras],
                wildcards=sorted(p.get('wildcard_options', ctl.wildcardOptions)),
                wildcardOptions=copy.deepcopy(p.get('wildcard_options', ctl.wildcardOptions)),
                wildcardTooltips=dict(ctl.wildcardTooltips),
                lastSeed=g['seed'], familyLabel=family.get('label', ''),
                note='Saved output settings. Unrecorded fields use model defaults; edits here are temporary.')
