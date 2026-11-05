#!/usr/bin/env python3
"""Test cache transactions and encoder cleanup using CPU-only stand-ins."""
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS, ModuleType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Settings
from sampling import sample_prompts, refresh_cache, encode_new_prompts

prompts = sample_prompts(Settings(sample_prompt='one\nline\n\ntwo', sample_count=3))
assert len(prompts) == 6 and prompts[0]['prompt'] == 'one\nline'
assert [p['seed'] for p in prompts] == [42, 43, 44, 42, 43, 44]
cache = {'one\nline': [1], '': [0], 'old': [3]}
calls = []
updated = refresh_cache(cache, prompts, lambda texts: calls.append(texts) or {'two': [2]})
assert calls == [['two']] and 'old' not in updated and 'old' in cache
refresh_cache(updated, prompts, lambda _: (_ for _ in ()).throw(AssertionError('unnecessary encoding')))
try:
    refresh_cache(cache, prompts, lambda _: (_ for _ in ()).throw(RuntimeError('encoder failed')))
except RuntimeError:
    pass
assert cache == {'one\nline': [1], '': [0], 'old': [3]}

class Model:
    def __init__(self):
        self.moves = []
    def to(self, device):
        self.moves.append(device)
        return self
    def eval(self):
        return self
    def requires_grad_(self, value):
        return self
    def parameters(self):
        return []
    def buffers(self):
        return []

for fail in (False, True):
    dit = Model()
    dit.blocks_to_swap = 1
    resident, streamed = Model(), Model()
    dit.layers = [resident, streamed]
    dit.offloader = NS(is_stream=[False, True], copier=NS(sync=lambda: None))
    dit.move_to_device_except_swap_blocks = dit.to
    encoder = Model()
    tensor = NS(detach=lambda: NS(cpu=lambda: 'embedding'))
    def encode(*args):
        if fail:
            raise RuntimeError('synthetic encoding error')
        return [tensor]
    token_strategy = NS(tokenize=lambda text: text)
    modules = {
        'torch': NS(bfloat16='bf16', random=NS(fork_rng=lambda **kw: nullcontext()),
                    cuda=NS(synchronize=lambda device: None), no_grad=nullcontext),
        'library': ModuleType('library'),
        'library.moss_image_utils': NS(load_text_encoder=lambda *a, **kw: encoder),
        'library.strategy_base': NS(TokenizeStrategy=NS(get_strategy=lambda: token_strategy),
                                    TextEncodingStrategy=NS(get_strategy=lambda: NS(encode_tokens=encode))),
        'library.device_utils': NS(clean_memory_on_device=lambda device: None),
        'library.safetensors_utils': NS(get_split_weight_filenames=lambda path: [path]),
    }
    with tempfile.NamedTemporaryFile() as model, patch.dict(sys.modules, modules):
        args = NS(text_encoder=model.name, disable_mmap_load_safetensors=False,
                  convrot_int8_text_encoder=True, convrot_int8_bwd=False)
        accelerator = NS(device='cuda:0', unwrap_model=lambda model: model)
        try:
            result = encode_new_prompts(args, accelerator, dit, ['new prompt'])
            assert not fail and result == {'new prompt': ['embedding']}
        except RuntimeError as exc:
            assert fail and str(exc) == 'synthetic encoding error'
    assert dit.moves == ['cpu', 'cuda:0']
    assert resident.moves == ['cpu', 'cuda:0'] and streamed.moves == []
    assert encoder.moves == ['cuda:0']
print('Prompt expansion, cache reuse, encoder failure cleanup and streamed block isolation OK')
