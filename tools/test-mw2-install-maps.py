import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('maps', Path(__file__).with_name('mw2-install-maps.py'))
maps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maps)


class AssetInstallTests(unittest.TestCase):
    def test_bad_download_never_replaces_a_cached_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'; source.write_bytes(b'bad')
            cached = root / 'cache/map.ff'; cached.parent.mkdir(); cached.write_bytes(b'old')
            entry = {'path': 'map.ff', 'url': source.as_uri(), 'size': 3,
                     'algorithm': 'sha1', 'hash': hashlib.sha1(b'new').hexdigest()}
            with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                maps.fetch(cached.parent, entry, 'unused')
            self.assertEqual(cached.read_bytes(), b'old')
            self.assertEqual(list(cached.parent.iterdir()), [cached])
            source.write_bytes(b'new')
            maps.fetch(cached.parent, entry, 'unused')
            self.assertEqual(cached.read_bytes(), b'new')

    def test_paths_cannot_escape_into_profiles_or_other_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ['../outside.ff', '/outside.ff', 'players/iw4x.stat']:
                with self.assertRaises(ValueError):
                    maps.destination(root, {'path': path})
            (root / 'link').symlink_to(root.parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                maps.destination(root, {'path': 'link/outside.ff'})


if __name__ == '__main__':
    unittest.main()
