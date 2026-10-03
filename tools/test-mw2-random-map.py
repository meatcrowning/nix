import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'maps', Path(__file__).resolve().parents[1] / 'home/prog/modern-warfare-2-maps.py')
maps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maps)


class RandomMapTests(unittest.TestCase):
    def test_only_installed_playable_maps_enter_the_bag(self):
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory)
            for name in ('zone/english/mp_base.ff', 'zone/english/mp_base_load.ff',
                         'zone/iw4x/x86/dlc/mp_dlc.ff', 'zone/iw4x/x86/dlc/mp_dlc_load.ff',
                         'zone/english/mp_incomplete.ff', 'zone/english/so_training.ff',
                         'usermaps/mp_custom/mp_custom.ff',
                         'usermaps/mp_custom/mp_custom_load.ff',
                         'usermaps/mp_custom/mp_custom.arena'):
                path = game / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'asset')
            menu = '\n'.join(f'\t\tLOCAL_MAP_SELECTION(0, "{name}", "title")'
                             for name in ('mp_base', 'mp_base', 'mp_dlc', 'mp_missing', 'mp_incomplete'))
            self.assertEqual(maps.installed_maps(game, menu), ['mp_base', 'mp_custom', 'mp_dlc'])
            (game / 'usermaps/mp_custom/mp_custom.arena').unlink()
            self.assertIn('mp_custom', maps.installed_maps(game, menu))
            (game / 'usermaps/mp_custom/mp_custom.ff').unlink()
            self.assertEqual(maps.installed_maps(game, menu), ['mp_base', 'mp_dlc'])

    def test_picker_defers_choice_until_start(self):
        menu = '\t\tLOCAL_MAP_SELECTION(0, "mp_base", "title")\nuiScript "ApplyMap";'
        rendered = maps.render_menu(menu, ['mp_dlc', 'mp_base'])
        self.assertIn('setdvar "nix_random_map" 1;', rendered)
        self.assertNotIn('setdvar ui_mapname', rendered)
        self.assertIn('setdvar "nix_random_map" 0; uiScript "ApplyMap";', rendered)
        self.assertEqual(maps.render_menu(menu, []), menu)

    def test_lobby_hides_preview_and_selects_before_start(self):
        lobby = '''
        itemDef
        {
            visible 1
            exp material "preview_" + dvarstring(ui_mapname);
        }
        itemDef
        {
            visible 1
            exp text dvarstring(party_mapname);
        }
        action { exec xpartygo; }
'''
        rendered = maps.render_lobby(lobby, ['mp_dlc', 'mp_base'])
        self.assertIn('dvarstring("nix_random_map") == "1"', rendered)
        self.assertIn('setLocalVarInt "nix_random_map_index" (milliseconds() % 2)', rendered)
        self.assertIn('exp text ("Random map")', rendered)
        self.assertEqual(rendered.count('setdvar ui_mapname'), 2)
        self.assertLess(rendered.index('setdvar ui_mapname'), rendered.index('exec xpartygo'))
        self.assertEqual(rendered.count('visible when (dvarstring("nix_random_map") != "1")'), 2)


if __name__ == '__main__':
    unittest.main()
