#!/usr/bin/env python3
"""Exercise the actual adapter against an in-memory trainer, never a GPU."""
import argparse
import io
import json
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import worker
from core import Settings, prepare_run, REVISION


class Accelerator:
    def unwrap_model(self, model):
        return model

    def save_state(self, path):
        Path(path).mkdir()
        (Path(path) / 'optimizer.bin').write_bytes(b'fake optimizer')


class Backend:
    samples = []
    def post_process_network(self, *a):
        pass

    def on_step_start(self, *args, **kwargs):
        pass

    def sample_images(self, accelerator, args, epoch, step, *a):
        self.samples.append(step)

    def _save_model(self, **kw):
        (Path(kw['args'].output_dir) / kw['ckpt_name']).write_bytes(b'fake lora')

    def train(self, args):
        accelerator = Accelerator()
        self.sample_prompts_te_outputs = {Settings().sample_prompt: [], '': []}
        network = types.SimpleNamespace(multiplier=1.0)
        network.set_multiplier = lambda value: setattr(network, 'multiplier', value)
        self.post_process_network(args, accelerator, network)
        self.sample_images(accelerator, args, 0, 0)
        self.on_step_start(args, accelerator, network)
        for step in range(1, args.max_train_steps + 1):
            self.sample_images(accelerator, args, None, step, object())


def parser():
    class Parser:
        def parse_args(self, args):
            return types.SimpleNamespace(output_name='test', output_dir=args[args.index('--output_dir') + 1],
                max_train_steps=int(args[args.index('--max_train_steps') + 1]))
    return Parser()


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    data = root / 'input'
    data.mkdir()
    (data / 'image.png').touch()
    (data / 'second.png').touch()
    model = root / 'model'
    model.touch()
    run = prepare_run(Settings(dataset=str(data), output=str(root / 'out'), dit=str(model),
        text_encoder=str(model), vae=str(model), steps=99, epochs=2, training_unit='epochs', sample_every=2, save_every=2))
    (root / 'revision').write_text(REVISION)
    modules = {'torch': types.SimpleNamespace(bfloat16='bf16'),
               'moss_image_train_network': types.SimpleNamespace(MossImageNetworkTrainer=Backend, setup_parser=parser),
               'library': types.ModuleType('library'),
               'library.args': types.SimpleNamespace(verify_command_line_training_args=lambda args: None)}
    output = io.StringIO()
    with patch.dict(sys.modules, modules), patch.object(worker, 'ENGINE', root), \
         patch.object(worker.Lease, 'acquire'), patch.object(worker.Lease, 'close'), \
         patch.object(worker.Controls, 'read'), patch.object(sys, 'stdout', output), \
         patch.object(sys, 'argv', ['worker.py', str(run)]):
        worker.main()
    assert Backend.samples == [2, 4]
    latest = json.loads((run / 'latest.json').read_text())
    assert latest['step'] == 4 and Path(latest['lora']).is_file()
    assert (Path(latest['state']) / 'optimizer.bin').is_file()
    assert json.loads((Path(latest['state']) / 'trainer-state.json').read_text())['step'] == 4
    assert 'completed' in output.getvalue()
    progress = [json.loads(line.removeprefix('TRAINER:')) for line in output.getvalue().splitlines()
                if line.startswith('TRAINER:') and '"event": "progress"' in line]
    assert [(e['step'], e['current_epoch'], e['epoch_step']) for e in progress] == [
        (1, 1, 1), (2, 1, 2), (3, 2, 1), (4, 2, 2)]
    assert all(e['total'] == 4 and e['total_epochs'] == 2 for e in progress)
    print('Adapter scheduling, complete checkpoint publication and progress OK')

    # Disable at step 1, then enable with new prompts and baseline at step 3.
    from sampling import LIVE_KEYS
    disabled = Settings(sample_enabled=False)
    enabled = Settings(sample_enabled=True, sample_baseline=True, sample_every=1,
                       sample_count=3, sample_entries=[{'prompt': 'new portrait', 'seed': 11},
                           {'prompt': 'a landscape', 'seed': 12}, {'prompt': 'new portrait', 'seed': 13}])
    requests = [{**{k: getattr(x, k) for k in LIVE_KEYS}, 'request_id': i}
                for i, x in enumerate((disabled, enabled))]
    observations = []
    def capture(self, accelerator, args, epoch, step, *a):
        observations.append((step, args.output_name, self.network.multiplier,
                             len(json.loads((run / 'prompts.json').read_text()))))
    with patch.dict(sys.modules, modules), patch.object(worker, 'ENGINE', root), \
         patch.object(worker.Lease, 'acquire'), patch.object(worker.Lease, 'close'), \
         patch.object(worker.Controls, 'read'), patch.object(sys, 'stdout', io.StringIO()), \
         patch.object(sys, 'argv', ['worker.py', str(run)]), \
         patch.object(worker.Controls, 'take_sampling', side_effect=[requests[0], None, requests[1], None]), \
         patch.object(worker, 'encode_new_prompts', side_effect=lambda args, acc, unet, texts: {t: [] for t in texts}), \
         patch.object(Backend, 'sample_images', capture):
        worker.main()
    assert observations == [(3, 'test-baseline', 0.0, 3), (3, 'test', 1.0, 3), (4, 'test', 1.0, 3)], observations
    # Resume/start uses persisted sampling and takes baseline before any steps.
    observations.clear()
    with patch.dict(sys.modules, modules), patch.object(worker, 'ENGINE', root), \
         patch.object(worker.Lease, 'acquire'), patch.object(worker.Lease, 'close'), \
         patch.object(worker.Controls, 'read'), patch.object(sys, 'stdout', io.StringIO()), \
         patch.object(sys, 'argv', ['worker.py', str(run)]), \
         patch.object(worker, 'encode_new_prompts', side_effect=lambda args, acc, unet, texts: {t: [] for t in texts}), \
         patch.object(Backend, 'sample_images', capture):
        worker.main()
    assert observations[0] == (0, 'test-baseline', 0.0, 3)
    assert all(row[2] == 1 for row in observations[1:])
    print('Live disable/re-enable, prompt/count changes, baseline isolation and persistence OK')
