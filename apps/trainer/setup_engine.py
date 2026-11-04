"""Install an isolated, revision-pinned backend without modifying ComfyUI."""
import os
import subprocess
import sys
from core import ENGINE, REVISION


def run(*cmd, **kwargs):
    print('+ ' + ' '.join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), check=True, **kwargs)


def main():
    ENGINE.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (ENGINE / 'setup.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        source = ENGINE / 'sd-scripts'
        if not source.exists():
            run('git', 'init', source)
            run('git', '-C', source, 'remote', 'add', 'origin', 'https://github.com/kohya-ss/sd-scripts.git')
        run('git', '-C', source, 'fetch', '--depth', '1', 'origin', REVISION)
        run('git', '-C', source, 'checkout', '--detach', REVISION)
        python = ENGINE / '.venv/bin/python'
        base = os.environ.get('TRAINER_BASE_PYTHON', sys.executable)
        if not python.exists():
            run(base, '-m', 'venv', ENGINE / '.venv')
        run('uv', 'pip', 'install', '--python', python, 'torch==2.13.0', 'torchvision==0.28.0',
            '--index-url', 'https://download.pytorch.org/whl/cu130')
        run('uv', 'pip', 'install', '--python', python, '-r', source / 'requirements.txt', cwd=source)
        # NixOS cannot execute the generic-linux loader bundled with Triton.
        linker = os.environ.get('TRAINER_DYNAMIC_LINKER')
        if linker:
            for binary in (ENGINE / '.venv/lib').glob('python*/site-packages/triton/backends/nvidia/bin/*'):
                probe = subprocess.run(['patchelf', '--print-interpreter', str(binary)], capture_output=True, text=True)
                if probe.returncode == 0 and probe.stdout.strip().startswith('/lib64/'):
                    run('patchelf', '--set-interpreter', linker, binary)
        run(python, '-c', 'import torch, torchvision, transformers, diffusers, accelerate, bitsandbytes; print("Backend imports OK")')
        (ENGINE / 'revision').write_text(REVISION + '\n')
        print('Training engine ready.', flush=True)


if __name__ == '__main__':
    main()
