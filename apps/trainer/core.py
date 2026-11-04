"""Run manifests and sd-scripts configuration; no GUI or ML imports."""
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import uuid

REVISION = 'cb70b96858477e716a2096292ab8aab433277f38'
ENGINE = Path.home() / '.local/share/moss-trainer/engine'
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    tmp.replace(path)


@dataclass
class Settings:
    dataset: str = ''
    output: str = str(Path.home() / 'Pictures/trainer')
    name: str = 'moss-lora'
    fallback_caption: str = ''
    steps: int = 2000
    resolution: int = 512
    rank: int = 16
    learning_rate: float = 0.0001
    blocks_to_swap: int = 20
    sample_every: int = 250
    sample_unit: str = 'steps'
    sample_count: int = 2
    sample_prompt: str = 'A portrait in soft natural light.'
    negative_prompt: str = ''
    sample_width: int = 768
    sample_height: int = 768
    sample_steps: int = 30
    sample_cfg: float = 3.0
    seed: int = 42
    save_every: int = 250
    save_unit: str = 'steps'
    dit: str = str(Path.home() / 'comfy/models/diffusion_models/moss-image-base-dit-int8-convrot.safetensors')
    text_encoder: str = str(Path.home() / 'comfy/models/text_encoders/moss-image-qwen35-int8-convrot.safetensors')
    vae: str = str(Path.home() / 'comfy/models/vae/moss-image-vae.safetensors')

    @classmethod
    def load(cls, path):
        try:
            value = json.loads(Path(path).read_text())
            return cls(**{k: v for k, v in value.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def validate(self):
        if not Path(self.dataset).is_dir() or not self.dataset:
            raise ValueError('Choose a dataset folder.')
        if not self.name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in self.name):
            raise ValueError('Run name may contain letters, numbers, hyphens and underscores.')
        for key in ('dit', 'text_encoder', 'vae'):
            if not Path(getattr(self, key)).is_file():
                raise ValueError('Select the missing model file: ' + key)
        for key in ('steps', 'rank', 'resolution', 'sample_count', 'sample_steps'):
            if not 1 <= getattr(self, key) <= 1000000:
                raise ValueError('Invalid ' + key)
        if self.resolution % 16 or any(n < 256 or n > 2048 or n % 16 for n in (self.sample_width, self.sample_height)):
            raise ValueError('Image dimensions must be multiples of 16 (samples: 256–2048).')
        if not math.isfinite(self.learning_rate) or not 0 < self.learning_rate <= 0.01:
            raise ValueError('Learning rate must be between 0 and 0.01.')
        if not 0 <= self.blocks_to_swap <= 36:
            raise ValueError('CPU offload must be between 0 and 36 blocks.')
        if self.sample_every < 0 or self.save_every < 0:
            raise ValueError('Intervals must be zero (off) or positive.')
        if self.sample_unit not in ('steps', 'epochs') or self.save_unit not in ('steps', 'epochs'):
            raise ValueError('Interval units must be steps or epochs.')
        if self.sample_every and not self.sample_prompt.strip():
            raise ValueError('Enter a sample prompt or disable periodic samples.')


def prepare_run(settings):
    settings.validate()
    source = Path(settings.dataset).resolve()
    # Snapshot the list before creating output; an output inside the dataset
    # must never recursively ingest its own samples or cached inputs.
    output = Path(settings.output).expanduser().resolve()
    if output == source or source in output.parents:
        raise ValueError('Choose an output folder outside the dataset.')
    images = sorted(p for p in source.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    if not images:
        raise ValueError('No PNG, JPEG, WebP or BMP images found in this folder.')
    run = output / (datetime.now().strftime('%Y%m%d-%H%M%S-') + settings.name + '-' + uuid.uuid4().hex[:6])
    data = run / 'dataset'
    data.mkdir(parents=True)
    captioned = 0
    for i, original in enumerate(images):
        target = data / (f'{i:06d}' + original.suffix.lower())
        target.symlink_to(original)
        caption = original.with_suffix('.txt')
        text = caption.read_text(encoding='utf-8-sig') if caption.is_file() else settings.fallback_caption
        captioned += caption.is_file()
        # sd-scripts rejects zero-byte caption files. An absent file with
        # class_tokens='' is its supported unconditional-training path.
        if text.strip():
            target.with_suffix('.txt').write_text(text, encoding='utf-8')
    manifest = {'settings': asdict(settings), 'images': len(images), 'captioned': captioned,
                'revision': REVISION, 'sources': [str(p) for p in images]}
    atomic_json(run / 'run.json', manifest)
    # JSON quoted strings are valid TOML basic strings, including unusual paths.
    (run / 'dataset.toml').write_text(
        '[general]\ncaption_extension = ".txt"\nenable_multiline_caption = true\n'
        '[[datasets]]\n' + f'resolution = {settings.resolution}\nbatch_size = 1\n'
        'enable_bucket = true\nbucket_no_upscale = true\nbucket_reso_steps = 16\n'
        '[[datasets.subsets]]\n' + f'image_dir = {json.dumps(str(data))}\nnum_repeats = 1\nclass_tokens = ""\n')
    prompts = [{'prompt': settings.sample_prompt, 'negative_prompt': settings.negative_prompt,
                'width': settings.sample_width, 'height': settings.sample_height,
                'sample_steps': settings.sample_steps, 'scale': settings.sample_cfg,
                'seed': settings.seed + i} for i in range(settings.sample_count)]
    atomic_json(run / 'prompts.json', prompts)
    return run


def training_args(run, resume=None):
    run = Path(run)
    manifest = json.loads((run / 'run.json').read_text())
    s = Settings(**manifest['settings'])
    offset = 0
    if resume:
        state = json.loads((Path(resume) / 'trainer-state.json').read_text())
        offset = int(state['step'])
        if Path(state['run']).resolve() != run.resolve():
            raise ValueError('The checkpoint belongs to a different run.')
    if offset >= s.steps:
        raise ValueError('This run has already reached its training limit.')
    args = ['--pretrained_model_name_or_path', s.dit, '--text_encoder', s.text_encoder,
            '--vae', s.vae, '--dataset_config', str(run / 'dataset.toml'),
            '--output_dir', str(run), '--output_name', s.name,
            '--network_module', 'networks.lora_generic', '--network_dim', str(s.rank),
            '--network_alpha', str(s.rank), '--network_train_unet_only',
            '--learning_rate', str(s.learning_rate), '--optimizer_type', 'AdamW8bit',
            '--lr_scheduler', 'constant', '--max_train_steps', str(s.steps - offset),
            '--mixed_precision', 'bf16', '--save_precision', 'bf16', '--save_model_as', 'safetensors',
            '--gradient_checkpointing', '--cache_latents', '--cache_latents_to_disk',
            '--cache_text_encoder_outputs', '--cache_text_encoder_outputs_to_disk',
            '--convrot_int8', '--convrot_int8_text_encoder',
            '--timestep_sampling', 'truncated_logit_normal', '--logit_mean', '-1.09',
            '--logit_std', '0.95', '--discrete_flow_shift', '1.0',
            '--max_data_loader_n_workers', '0', '--seed', str(s.seed),
            '--sample_prompts', str(run / 'prompts.json')]
    if s.blocks_to_swap:
        args += ['--blocks_to_swap', str(s.blocks_to_swap), '--block_swap_h2d_only']
    if resume:
        # Preserve weights/optimizer/RNG, restart dataset traversal. Constant
        # LR avoids rebuilding a different schedule for the remaining steps.
        args += ['--resume', str(resume), '--initial_step', '0']
    return args, offset, manifest
