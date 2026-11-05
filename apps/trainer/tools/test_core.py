#!/usr/bin/env python3
"""Isolated manifest and cooperative-control tests; no GPU or user data."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Settings, prepare_run, training_args, total_training_steps
from control import Controls


class Tests(unittest.TestCase):
    def test_captionless_mixed_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'images with # spaces'
            data.mkdir()
            (data / 'a.jpg').write_bytes(b'image')
            (data / 'a.txt').write_text('A caption\nwith lines.')
            (data / 'b.png').write_bytes(b'image')
            (data / 'c.png').write_bytes(b'image')
            (data / 'c.txt').touch()
            model = root / 'model'
            model.touch()
            s = Settings(dataset=str(data), output=str(root / 'runs'), dit=str(model),
                         text_encoder=str(model), vae=str(model), sample_prompt='a "quoted" prompt\n--s 99')
            run = prepare_run(s)
            self.assertEqual((run / 'dataset/000000.txt').read_text(), 'A caption\nwith lines.')
            self.assertFalse((run / 'dataset/000001.txt').exists())
            self.assertFalse((data / 'b.txt').exists())
            self.assertTrue((run / 'dataset/000000.jpg').is_symlink())
            args, offset, manifest = training_args(run)
            self.assertIn('--network_train_unet_only', args)
            self.assertEqual(offset, 0)
            self.assertEqual(float(args[args.index('--network_alpha') + 1]), 1.0)
            self.assertEqual(manifest['captioned'], 2)
            self.assertFalse((run / 'dataset/000002.txt').exists())
            self.assertEqual(json.loads((run / 'prompts.json').read_text())[0]['prompt'], s.sample_prompt)
            import tomllib
            parsed = tomllib.loads((run / 'dataset.toml').read_text())
            self.assertEqual(parsed['datasets'][0]['subsets'][0]['image_dir'], str(run / 'dataset'))
            state = run / 'saved-state'
            state.mkdir()
            (state / 'trainer-state.json').write_text(json.dumps({'step': 200, 'run': str(run)}))
            args, offset, _ = training_args(run, state)
            self.assertEqual(offset, 200)
            self.assertEqual(args[args.index('--max_train_steps') + 1], '1800')
            # Old manifests remain step-based; epoch runs resume against their
            # original total rather than training a fresh set of epochs.
            self.assertEqual(total_training_steps(manifest), 2000)
            manifest['settings']['alpha'] = 4.5
            (run / 'run.json').write_text(json.dumps(manifest))
            custom_args, _, _ = training_args(run)
            self.assertEqual(float(custom_args[custom_args.index('--network_alpha') + 1]), 4.5)
            manifest['settings'].pop('alpha')
            (run / 'run.json').write_text(json.dumps(manifest))
            legacy_args, _, _ = training_args(run, state)
            self.assertEqual(float(legacy_args[legacy_args.index('--network_alpha') + 1]), s.rank)
            self.assertEqual(Settings.from_run(manifest['settings']).alpha, s.rank)
            manifest['settings'].pop('training_unit')
            manifest['settings'].pop('epochs')
            self.assertEqual(total_training_steps(manifest), 2000)
            manifest['settings'].update(training_unit='epochs', epochs=7)
            (run / 'run.json').write_text(json.dumps(manifest))
            (state / 'trainer-state.json').write_text(json.dumps({'step': 4, 'run': str(run)}))
            args, offset, _ = training_args(run, state)
            self.assertEqual(offset, 4)
            self.assertEqual(args[args.index('--max_train_steps') + 1], '17')
            (state / 'trainer-state.json').write_text(json.dumps({'step': 21, 'run': str(run)}))
            with self.assertRaises(ValueError):
                training_args(run, state)
            s.output = str(data / 'output')
            with self.assertRaises(ValueError):
                prepare_run(s)

    def test_pause_save_resume_stop(self):
        control = Controls()
        paused = threading.Event()
        saved = threading.Event()
        events = []
        def event(state):
            events.append(state)
            if state == 'paused':
                paused.set()
        control.submit('pause')
        result = []
        thread = threading.Thread(target=lambda: result.append(control.boundary(saved.set, event)))
        thread.start()
        self.assertTrue(paused.wait(2))
        self.assertTrue(thread.is_alive())
        control.submit('save')
        self.assertTrue(saved.wait(2))
        self.assertTrue(thread.is_alive())
        control.submit('resume')
        thread.join(2)
        self.assertEqual(result, [True])
        control.submit('stop')
        saved.clear()
        self.assertFalse(control.boundary(saved.set, event))
        self.assertTrue(saved.is_set())

    def test_gui_loss_requests_save(self):
        control = Controls()
        control.read(io.StringIO('not json\n'))
        saved = []
        self.assertFalse(control.boundary(lambda: saved.append(1), lambda _: None))
        self.assertEqual(saved, [1])


if __name__ == '__main__':
    unittest.main()
