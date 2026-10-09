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

    def test_native_modes_use_existing_launcher_without_shell_parsing(self):
        game = {'name': 'Example', 'runner': 'native', 'path': '/bin/example',
                'modes': [{'id': 'campaign', 'args': ['--campaign']},
                          {'id': 'zombies', 'args': ['--zombies']}]}
        self.assertEqual(games.command(game, 'zombies'), (['/bin/example', '--zombies'], None))
        self.assertEqual(games.command(game), (['/bin/example'], None))
        with self.assertRaises(ValueError):
            games.command(game, 'unrecognised')

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

    def test_native_steam_input_is_opt_in_and_only_applies_inside_steam(self):
        for runner in ('native', 'steam-run'):
            game = {'runner': runner, 'steamInput': True}
            env = {'DISPLAY': ':77', 'LD_PRELOAD': '/overlay.so'}
            steam_session.configure(game, [runner], env, self.root)
            self.assertNotIn('SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT', env)
            env['SteamGameId'] = '123456789'
            steam_session.configure(game, [runner], env, self.root)
            self.assertEqual(env['SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT'], '0x28de,0x11ff')
            self.assertEqual(env['SDL_JOYSTICK_HIDAPI'], '0')
            self.assertEqual(env['LD_PRELOAD'], '/overlay.so')
            unmanaged = {'SteamGameId': '123456789'}
            steam_session.configure({'runner': runner}, [runner], unmanaged, self.root)
            self.assertNotIn('SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT', unmanaged)

    def test_menu_uses_curated_artwork_without_text_or_cropping(self):
        hero = self.root / 'hero-curated.png'
        Image.new('RGB', (920, 300), 'red').save(hero)
        header = self.root / 'wide.jpg'
        Image.new('RGB', (460, 215), 'blue').save(header)
        assets = steam_art.complete({'name': 'Example Game'}, {'': header}, self.root)
        with Image.open(assets['_logo']) as image:
            self.assertEqual(image.size, (920, 300))
            self.assertEqual(image.getcolors(), [(920 * 300, (255, 0, 0))])
        self.assertEqual(assets[''], header)

    def test_missing_art_is_not_replaced_with_generated_text(self):
        self.assertEqual(steam_art.complete({'name': 'Example'}, {}, self.root), {})
        self.assertEqual(list(self.root.iterdir()), [])

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
        legacy = self.root / 'art/example/logo-fallback.png'
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b'generated-title')
        (grid / f'{2**32-10}_logo.png').write_bytes(legacy.read_bytes())
        header = grid / f'{2**32-10}.png'; header.write_bytes(b'user-banner')
        logo = self.root / 'logo.png'; Image.new('RGBA', (10, 10)).save(logo)
        with patch.object(games, 'STEAM', self.root), patch.object(games, 'ART', self.root/'art'), patch.object(games, 'GAMES_BIN', '/bin/games'), \
             patch.object(games, 'artwork', return_value={'p': logo, '_logo': logo, '': logo}), \
             patch('subprocess.run') as run:
            run.return_value.returncode = 1
            games.repair_steam([{'slug': 'example', 'name': 'Example',
                                 'runner': 'steam-run', 'steamInput': True}])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(portrait.read_bytes(), b'user-art')
        self.assertEqual(header.read_bytes(), b'user-banner')
        self.assertEqual((grid / f'{2**32-10}_logo.png').read_bytes(), logo.read_bytes())
        apps = vdf.loads(local.read_text())['UserLocalConfigStore']['apps']
        self.assertEqual(apps['123']['UseSteamControllerConfig'], '0')
        self.assertEqual(apps[str(2**32-10)], {'OtherSetting': 'keep', 'UseSteamControllerConfig': '2'})


if __name__ == '__main__':
    unittest.main()
