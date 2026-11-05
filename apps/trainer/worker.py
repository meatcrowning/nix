"""Thin adapter around pinned sd-scripts; ML lives in the separate engine env."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import traceback
import urllib.request
import uuid

from control import Controls
from core import ENGINE, REVISION, atomic_json, training_args, total_training_steps


def emit(event, **values):
    print('\nTRAINER:' + json.dumps(dict(event=event, **values)), flush=True)


class Lease:
    def __init__(self):
        self.token = uuid.uuid4().hex
        self.closed = threading.Event()

    def post(self, action):
        body = json.dumps({'backend': 'trainer', 'token': self.token, 'lease': 120,
                           'bytes': 12 * 1024**3}).encode()
        request = urllib.request.Request(os.environ.get('AI_WARDEN_URL', 'http://127.0.0.1:8199') + '/' + action + '-owned',
                                         data=body, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.load(response)
        except (OSError, ValueError) as exc:
            return {'ok': True, 'bypassed': True, 'reason': 'GPU coordination unavailable: ' + str(exc)}

    def acquire(self):
        result = self.post('reserve')
        if not result.get('ok'):
            raise RuntimeError(result.get('reason', 'GPU is busy.'))
        if result.get('bypassed'):
            emit('warning', message=result.get('reason', 'GPU coordination unavailable.'))
        threading.Thread(target=self.heartbeat, daemon=True).start()

    def heartbeat(self):
        while not self.closed.wait(20):
            result = self.post('renew')
            if not result.get('ok') or result.get('bypassed'):
                emit('warning', message='GPU reservation lost; save and stop before starting another GPU job.')

    def close(self):
        self.closed.set()
        self.post('done')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--check', action='store_true')
    opts = parser.parse_args()
    run = opts.run.resolve()
    argv, offset, manifest = training_args(run, opts.resume)
    if manifest['revision'] != REVISION or (ENGINE / 'revision').read_text().strip() != REVISION:
        raise RuntimeError('Training engine version does not match this run.')
    sys.path.insert(0, str(ENGINE / 'sd-scripts'))
    import torch
    from moss_image_train_network import MossImageNetworkTrainer, setup_parser
    import library.args as args_util
    args = setup_parser().parse_args(argv)
    args_util.verify_command_line_training_args(args)
    if opts.check:
        from library import config_util
        generator = config_util.BlueprintGenerator(config_util.ConfigSanitizer(True, True, args.masked_loss, True))
        generator.generate(config_util.load_user_config(args.dataset_config), args)
        print('MOSS training imports, arguments and dataset schema OK')
        return
    controls = Controls()
    threading.Thread(target=controls.read, args=(sys.stdin,), daemon=True).start()
    s = manifest['settings']
    total = total_training_steps(manifest)
    steps_per_epoch = manifest['images']
    total_epochs = (total + steps_per_epoch - 1) // steps_per_epoch
    lease = Lease()

    class Stopped(Exception):
        pass

    class Trainer(MossImageNetworkTrainer):
        network = None
        saved_step = -1

        def on_step_start(self, args, accelerator, network, *a, **kw):
            self.network = accelerator.unwrap_model(network)
            return super().on_step_start(args, accelerator, network, *a, **kw)

        def sample_images(self, accelerator, args, epoch, global_step, *a):
            if epoch == 0:  # initial callback has no trained network yet
                emit('status', state='training')
                return
            if epoch is not None:  # step callback owns scheduling and controls
                return
            step = global_step + offset
            epoch_number = step / manifest['images']
            emit('progress', step=step, total=total, epoch=epoch_number,
                 current_epoch=(step - 1) // steps_per_epoch + 1, total_epochs=total_epochs,
                 epoch_step=(step - 1) % steps_per_epoch + 1, steps_per_epoch=steps_per_epoch)

            def save():
                if self.saved_step == step:
                    return
                emit('status', state='saving')
                name = f"{s['name']}-step{step:08d}-{uuid.uuid4().hex[:6]}"
                pending = run / ('.' + name + '-state.pending')
                accelerator.save_state(str(pending))
                atomic_json(pending / 'trainer-state.json', {'step': step, 'run': str(run)})
                state = run / (name + '-state')
                pending.rename(state)
                temporary = '.' + name + '.safetensors'
                self._save_model(args=args, accelerator=accelerator, save_dtype=torch.bfloat16,
                                 ckpt_name=temporary, unwrapped_nw=self.network,
                                 steps=step, epoch_no=int(epoch_number))
                target = run / (name + '.safetensors')
                (run / temporary).rename(target)
                atomic_json(run / 'latest.json', {'state': str(state), 'lora': str(target), 'step': step})
                self.saved_step = step
                emit('saved', path=str(target), state=str(state), step=step)

            def due(interval, unit):
                interval = interval * manifest['images'] if unit == 'epochs' else interval
                return interval > 0 and step % interval == 0

            if due(s['save_every'], s['save_unit']) or step >= total:
                save()
            if not controls.boundary(save, lambda state: emit('status', state=state)):
                emit('status', state='stopped')
                raise Stopped()
            if due(s['sample_every'], s['sample_unit']):
                emit('status', state='sampling')
                args.sample_every_n_steps = 1
                args.sample_every_n_epochs = None
                super().sample_images(accelerator, args, None, step, *a)
                emit('samples')
                if not controls.boundary(save, lambda state: emit('status', state=state)):
                    emit('status', state='stopped')
                    raise Stopped()
            emit('status', state='training')

    emit('status', state='reserving GPU')
    try:
        lease.acquire()
        if controls.stopping:
            emit('status', state='stopped')
            return
        emit('status', state='preparing model and caches')
        try:
            Trainer().train(args)
        except Stopped:
            return
        latest = json.loads((run / 'latest.json').read_text())
        if latest['step'] != total:
            raise RuntimeError('The backend ended before the requested training limit; see the log.')
        emit('status', state='completed')
    finally:
        lease.close()


if __name__ == '__main__':
    try:
        import fcntl
        with (ENGINE / 'setup.lock').open('a') as engine_lock:
            fcntl.flock(engine_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            main()
    except Exception as exc:
        emit('error', message=str(exc))
        traceback.print_exc()
        sys.exit(1)
