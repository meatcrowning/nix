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
    def on_step_start(self, *args, **kwargs):
        pass

    def sample_images(self, accelerator, args, epoch, step, *a):
        self.samples.append(step)

    def _save_model(self, **kw):
        (Path(kw['args'].output_dir) / kw['ckpt_name']).write_bytes(b'fake lora')

    def train(self, args):
        accelerator = Accelerator()
        self.sample_images(accelerator, args, 0, 0)
        self.on_step_start(args, accelerator, object())
        for step in range(1, args.max_train_steps + 1):
            self.sample_images(accelerator, args, None, step)


def parser():
    class Parser:
        def parse_args(self, args):
            return types.SimpleNamespace(output_dir=args[args.index('--output_dir') + 1],
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
