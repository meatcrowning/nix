#!/usr/bin/env python3
"""CPU-only contract test against the installed, pinned sd-scripts backend."""
import os
from pathlib import Path
import sys
import tempfile

assert os.environ.get('CUDA_VISIBLE_DEVICES') == '', 'Run with CUDA_VISIBLE_DEVICES empty'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import ENGINE, Settings, prepare_run, training_args
sys.path.insert(0, str(ENGINE / 'sd-scripts'))
from PIL import Image
from moss_image_train_network import setup_parser
from library import config_util
from library.dreambooth_dataset import read_caption

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    dataset = root / 'input'
    dataset.mkdir()
    for name in ('captioned', 'uncaptioned', 'empty'):
        Image.new('RGB', (512, 512)).save(dataset / (name + '.png'))
    (dataset / 'captioned.txt').write_text('A synthetic fixture.\nSecond line.')
    (dataset / 'empty.txt').touch()
    model = root / 'model'
    model.touch()
    run = prepare_run(Settings(dataset=str(dataset), output=str(root / 'out'), dit=str(model),
                              text_encoder=str(model), vae=str(model)))
    captions = [read_caption(str(p), '.txt', False, True) for p in sorted((run / 'dataset').glob('*.png'))]
    assert captions == ['A synthetic fixture.\nSecond line.', None, None], captions
    args = setup_parser().parse_args(training_args(run)[0])
    generator = config_util.BlueprintGenerator(config_util.ConfigSanitizer(True, True, args.masked_loss, True))
    blueprint = generator.generate(config_util.load_user_config(args.dataset_config), args)
    group, _ = config_util.generate_dataset_group_by_blueprint(blueprint.dataset_group)
    assert len(group) == 3
    assert sorted(group.datasets[0].image_data[k].caption for k in group.datasets[0].image_data) == ['', '', 'A synthetic fixture.\nSecond line.']
    assert not list(dataset.glob('*.npz'))
    print('Real backend accepts captioned, empty and absent captions; 3 training batches OK')
