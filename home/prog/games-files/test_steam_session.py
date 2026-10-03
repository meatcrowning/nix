"""No emulator, controller device, Steam process, or live display is opened."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('GAMES_MANIFEST', '/nonexistent/test-manifest')
os.environ.setdefault('GAMES_RETROARCH_CORES', '/nonexistent/test-cores')
import games
import steam_art
import steam_session
import vdf
from PIL import Image


class SteamTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_direct_launch_is_unchanged_and_creates_no_files(self):
        env = {'WAYLAND_DISPLAY': 'wayland-0'}
        argv = ['retroarch', '-L', '/core.so', '/game.rom']
        self.assertEqual(steam_session.configure({'runner': 'retroarch'}, argv, env, self.root), argv)
        self.assertEqual(env, {'WAYLAND_DISPLAY': 'wayland-0'})
        self.assertEqual(list(self.root.iterdir()), [])

    def test_steam_emulator_uses_only_virtual_pad_and_preserves_overlay(self):
        for runner in ('retroarch', 'pcsx2'):
            env = {'SteamGameId': '123456789', 'DISPLAY': ':77',
                   'WAYLAND_DISPLAY': 'wayland-0', 'LD_PRELOAD': '/overlay.so'}
            argv = steam_session.configure({'runner': runner}, [runner, '/game'], env, self.root)
            self.assertEqual(env['DISPLAY'], ':77')
            self.assertEqual(env['LD_PRELOAD'], '/overlay.so')
            self.assertEqual(env['SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT'], '0x28de,0x11ff')
            self.assertTrue(env['WAYLAND_DISPLAY'].startswith('/nonexistent/'))
            self.assertEqual(env['SDL_VIDEODRIVER'], 'x11')
            if runner == 'retroarch':
                config = Path(argv[2]).read_text()
                self.assertIn('input_menu_toggle_gamepad_combo = "4"', config)
                self.assertIn('input_menu_toggle_btn = "nul"', config)
                self.assertIn('input_player1_select_btn = "4"', config)
                self.assertIn('input_player1_start_btn = "6"', config)
                self.assertIn('input_autodetect_enable = "false"', config)
                self.assertIn('config_save_on_exit = "false"', config)
                self.assertNotIn('input_player1_start_btn = "5"', config)  # SDL Guide

    def test_artwork_fallbacks_decode_and_keep_curated_assets(self):
        cover = self.root / 'p.png'
        Image.new('RGB', (100, 200), 'red').save(cover)
        assets = steam_art.complete({'name': 'Example Game'}, {'p': cover}, self.root)
        with Image.open(assets['_logo']) as logo:
            self.assertEqual(logo.mode, 'RGBA')
            self.assertEqual(logo.getpixel((0, 0))[3], 0)
            self.assertIsNotNone(logo.getbbox())
        with Image.open(assets['']) as header:
            self.assertEqual(header.size, (920, 430))
        curated = self.root / 'logo-curated.png'
        Image.new('RGBA', (40, 20), 'blue').save(curated)
        completed = steam_art.complete({'name': 'Example'}, {'': cover}, self.root)
        self.assertEqual(completed['_logo'], curated)
        self.assertEqual(completed[''], cover)

    def test_repair_preserves_shortcuts_art_and_unrelated_settings(self):
        config = self.root / 'userdata/123/config'
        config.mkdir(parents=True)
        shortcuts = {'shortcuts': {'0': {'appid': -10, 'AppName': 'Example',
            'Exe': '"/bin/games"', 'LaunchOptions': 'run example', 'LastPlayTime': 42}}}
        path = config / 'shortcuts.vdf'
        original = vdf.binary_dumps(shortcuts)
        path.write_bytes(original)
        local = config / 'localconfig.vdf'
        local.write_text(vdf.dumps({'UserLocalConfigStore': {'apps': {
            '123': {'UseSteamControllerConfig': '0'},
            str(2**32-10): {'OtherSetting': 'keep'}}}}))
        grid = config / 'grid'; grid.mkdir()
        portrait = grid / f'{2**32-10}p.png'; portrait.write_bytes(b'user-art')
        logo = self.root / 'logo.png'; Image.new('RGBA', (10, 10)).save(logo)
        with patch.object(games, 'STEAM', self.root), patch.object(games, 'GAMES_BIN', '/bin/games'), \
             patch.object(games, 'artwork', return_value={'p': logo, '_logo': logo}), \
             patch('subprocess.run') as run:
            run.return_value.returncode = 1
            games.repair_steam([{'slug': 'example', 'name': 'Example', 'runner': 'retroarch'}])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(portrait.read_bytes(), b'user-art')
        self.assertEqual((grid / f'{2**32-10}_logo.png').read_bytes(), logo.read_bytes())
        apps = vdf.loads(local.read_text())['UserLocalConfigStore']['apps']
        self.assertEqual(apps['123']['UseSteamControllerConfig'], '0')
        self.assertEqual(apps[str(2**32-10)], {'OtherSetting': 'keep', 'UseSteamControllerConfig': '2'})


if __name__ == '__main__':
    unittest.main()
