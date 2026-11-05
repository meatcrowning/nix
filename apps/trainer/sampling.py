"""Sampling requests and bounded text re-encoding between training steps."""
import gc
import os
from pathlib import Path
import re

LIVE_KEYS = ('sample_prompt', 'negative_prompt', 'sample_count', 'sample_enabled',
             'sample_baseline', 'sample_every', 'sample_unit')


class RestorationError(RuntimeError):
    """Training cannot continue if resident weights were not restored."""


def sample_prompts(settings):
    """Blank lines separate prompts; line breaks within a prompt are preserved."""
    prompts = [p.strip() for p in re.split(r'\n\s*\n', settings.sample_prompt.strip()) if p.strip()]
    prompts = list(dict.fromkeys(prompts))
    if settings.sample_unit not in ('steps', 'epochs') or not isinstance(settings.sample_every, int) or not 0 <= settings.sample_every <= 1000000:
        raise ValueError('Choose a valid sampling interval.')
    if not isinstance(settings.sample_enabled, bool) or not isinstance(settings.sample_baseline, bool):
        raise ValueError('Invalid sampling switch.')
    if not prompts:
        raise ValueError('Enter at least one sample prompt.')
    if not isinstance(settings.sample_count, int) or not 1 <= settings.sample_count <= 16:
        raise ValueError('Choose between 1 and 16 samples per prompt.')
    if len(prompts) * settings.sample_count > 64:
        raise ValueError('Use at most 64 samples in one sampling interval.')
    if len(settings.sample_prompt) + len(settings.negative_prompt) > 65536:
        raise ValueError('Sample prompts are too long (maximum 65536 characters).')
    return [{'prompt': prompt, 'negative_prompt': settings.negative_prompt,
             'width': settings.sample_width, 'height': settings.sample_height,
             'sample_steps': settings.sample_steps, 'scale': settings.sample_cfg,
             'seed': settings.seed + i}
            for prompt in prompts for i in range(settings.sample_count)]


def refresh_cache(cache, prompts, encode):
    texts = list(dict.fromkeys(p[k] for p in prompts for k in ('prompt', 'negative_prompt')))
    missing = [text for text in texts if text not in cache]
    # Commit nothing until every new embedding is available. A count-only
    # change never loads the encoder, and old prompts do not accumulate forever.
    additions = encode(missing) if missing else {}
    return {text: cache[text] if text in cache else additions[text] for text in texts}


def encode_new_prompts(args, accelerator, unet, texts):
    import torch
    from library import moss_image_utils, strategy_base
    from library.device_utils import clean_memory_on_device

    dit = accelerator.unwrap_model(unet)
    offloader = getattr(dit, 'offloader', None) if getattr(dit, 'blocks_to_swap', 0) else None
    if offloader and not hasattr(offloader, 'is_stream'):
        raise RuntimeError('Live prompt changes require the H2D-only offloader.')
    # Leave streamed blocks and their shared CPU masters/ring buffers alone.
    # Only resident weights move out; the upstream offloader retains ownership
    # of its streaming blocks, hooks, and transfer bookkeeping.
    resident = [b for i, b in enumerate(dit.layers) if not offloader.is_stream[i]] if offloader else []
    tensors = list(dit.parameters()) + list(dit.buffers())
    device_bytes = sum(t.numel() * t.element_size() for t in tensors if t.device.type == 'cuda')
    available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))
    from library.safetensors_utils import get_split_weight_filenames
    files = get_split_weight_filenames(args.text_encoder) or [args.text_encoder]
    if available < sum(os.path.getsize(path) for path in files) + device_bytes + 2 * 1024**3:
        raise RuntimeError('Not enough free system memory to encode new prompts; previous samples are unchanged.')
    del tensors
    encoder = None
    result = {}
    error = None
    tokenizer = strategy_base.TokenizeStrategy.get_strategy()
    encoding = strategy_base.TextEncodingStrategy.get_strategy()
    # Loading a model and encoding must not advance the training RNG sequence.
    with torch.random.fork_rng(devices=[accelerator.device]):
        torch.cuda.synchronize(accelerator.device)
        if offloader:
            offloader.copier.sync()
        try:
            if offloader:
                dit.move_to_device_except_swap_blocks('cpu')
                for block in resident:
                    block.to('cpu')
            else:
                dit.to('cpu')
            clean_memory_on_device(accelerator.device)
            encoder = moss_image_utils.load_text_encoder(
                args.text_encoder, dtype=torch.bfloat16, device='cpu',
                disable_mmap=args.disable_mmap_load_safetensors,
                convrot_int8=args.convrot_int8_text_encoder,
                convrot_int8_bwd=args.convrot_int8_bwd, calc_device=accelerator.device)
            encoder.eval().requires_grad_(False)
            encoder.to(accelerator.device)
            with torch.no_grad():
                for text in texts:
                    output = encoding.encode_tokens(tokenizer, [encoder], tokenizer.tokenize(text))
                    result[text] = [tensor.detach().cpu() for tensor in output]
                    del output
        except Exception as exc:
            # Drop failed model-loading frames before reclaiming/restoring VRAM.
            error = str(exc)
        finally:
            # Reclaim encoder VRAM before returning resident training weights.
            if encoder is not None:
                del encoder
            gc.collect()
            clean_memory_on_device(accelerator.device)
            try:
                if offloader:
                    dit.move_to_device_except_swap_blocks(accelerator.device)
                    for block in resident:
                        block.to(accelerator.device)
                else:
                    dit.to(accelerator.device)
            except Exception as exc:
                raise RestorationError('Could not restore training weights after encoding prompts') from exc
    if error is not None:
        raise RuntimeError(error)
    return result


def load_sampling(settings, run):
    path = Path(run) / 'sampling.json'
    if path.exists():
        import json
        for key, value in json.loads(path.read_text()).items():
            if key in LIVE_KEYS:
                setattr(settings, key, value)
    return settings
