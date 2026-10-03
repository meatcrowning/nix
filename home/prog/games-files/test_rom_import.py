"""Isolated import transactions; all user paths and external effects are replaced."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('GAMES_MANIFEST', '/nonexistent/test-manifest')
os.environ.setdefault('GAMES_RETROARCH_CORES', '/nonexistent/test-cores')
import games
import rom_import as rom
import msgpack


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        constants = {'HOME': root, 'DATA': root/'data', 'MANIFEST': root/'manifest.json',
                     'CORES': root/'cores', 'ENTRIES': root/'entries', 'ICONS': root/'icons',
                     'ART': root/'art', 'GAMES_BIN': '/test/bin/games'}
        for key, value in constants.items():
            p = patch.object(games, key, value); p.start(); self.addCleanup(p.stop)
        for key, value in {'IMPORTS':root/'data/games/imports.json', 'DETAILS':root/'data/games/library-details.json',
                           'CACHE':root/'cache'}.items():
            p = patch.object(rom,key,value); p.start(); self.addCleanup(p.stop)
        games.CORES.mkdir()
        (games.CORES / games.CORE_FILES['fceumm']).touch()
        self.path = root/'Example (USA).nes'; self.path.write_bytes(b'NES\x1aexample')
        self.entry = {'name':'Example (USA)', 'developer':'Studio', 'releaseyear':1991}
        self.request = {'path':str(self.path), 'system':'nes', 'match':self.entry['name']}
        for target, value in [('shutil.which','/test/emulator'), ('games.artwork',{}), ('games.fetch',False), ('rom_import.catalog',[self.entry])]:
            p=patch(target,return_value=value); p.start(); self.addCleanup(p.stop)

    def test_prepare_finish_retry_preserves_metadata_and_manifest(self):
        games.MANIFEST.write_text(json.dumps({'games':[], 'extraSaves':[{'name':'keep'}]}))
        before=games.MANIFEST.read_bytes()
        rom.atomic_json(rom.DETAILS, {'42':{'developer':'Unrelated'}})
        first=rom.prepare(self.request)
        self.assertEqual(first['details']['controllerSupport'],'emulated')
        rom.record({'slug':first['slug'],'appid':2147483650})
        self.assertFalse(games.load()[0]['importComplete'])
        self.assertFalse((games.ENTRIES / (f"game-{first['slug']}.desktop")).exists())
        rom.finish({'slug':first['slug'],'appid':2147483650})
        self.assertTrue(games.load()[0]['importComplete'])
        second=rom.prepare(self.request)
        self.assertEqual(first['slug'],second['slug'])
        self.assertEqual(second['existingAppId'],2147483650)
        self.assertEqual(len(games.load()),1)
        self.assertEqual(games.MANIFEST.read_bytes(),before)
        details=json.loads(rom.DETAILS.read_text())
        self.assertEqual(details['42']['developer'],'Unrelated')
        self.assertEqual(details['2147483650']['year'],'1991')
        argv,_=games.command(games.load()[0]); self.assertEqual(argv[-1],str(self.path))
        self.assertTrue((games.ENTRIES / (f"game-{first['slug']}.desktop")).exists())

    def test_existing_private_entry_is_reused_without_editing_private_data(self):
        game={'slug':'existing','name':'Existing name','path':str(self.path),'runner':'retroarch','core':'fceumm'}
        games.MANIFEST.write_text(json.dumps({'games':[game]}))
        prepared=rom.prepare(self.request)
        self.assertEqual(prepared['slug'],'existing')
        self.assertEqual(len(games.load()),1)
        self.assertEqual(games.load()[0]['name'],'Existing name')

    def test_same_title_at_another_path_does_not_overwrite_shortcut(self):
        rom.prepare(self.request)
        other=self.path.with_name('another.nes'); other.write_bytes(b'example')
        with self.assertRaisesRegex(ValueError,'different path'):
            rom.prepare({**self.request,'path':str(other)})
        self.assertEqual(len(games.load()),1)

    def test_missing_credits_require_user_completion(self):
        self.entry.pop('developer')
        with self.assertRaisesRegex(ValueError,'developer'): rom.prepare(self.request)
        self.assertFalse(rom.IMPORTS.exists())
        prepared=rom.prepare({**self.request,'developer':'Confirmed Studio'})
        self.assertEqual(prepared['details']['manualFields'],['developer'])

    def test_bad_paths_and_platforms_fail_before_changes(self):
        with self.assertRaises(ValueError): rom.prepare({**self.request,'system':'ps2'})
        with self.assertRaises(FileNotFoundError): rom.prepare({**self.request,'path':str(self.path)+'missing'})
        self.assertFalse(rom.IMPORTS.exists())

    def test_missing_core_is_reported(self):
        (games.CORES / games.CORE_FILES['fceumm']).unlink()
        with self.assertRaisesRegex(ValueError,'core is not installed'): rom.prepare(self.request)

    def test_cue_requires_its_disc_files(self):
        path=self.path.with_suffix('.cue'); path.write_text('FILE "missing.bin" BINARY\n')
        with self.assertRaisesRegex(ValueError,'Missing or invalid disc file'):
            rom.validate_file(str(path),rom.system('psx'))

    def test_catalog_duplicates_merge_credits_without_crossing_regions(self):
        entries=[self.entry, {'crc':b'1234', 'serial':b'CODE'}, {'name':self.entry['name'],'crc':b'1234'}, {'name':'Example (Japan)'}]
        data=b'RARCHDB\0'+b'\0'*8+b''.join(msgpack.packb(e) for e in entries)+msgpack.packb(None)
        decoded=rom.decode_catalog(data)
        self.assertEqual(len(decoded),2)
        self.assertEqual(decoded[0]['developer'],'Studio')
        self.assertNotIn('developer',decoded[1])
        with self.assertRaisesRegex(ValueError,'Incomplete'): rom.decode_catalog(data[:-1])

    def test_search_returns_console_specific_choices_and_never_adds(self):
        result=rom.search({**self.request,'query':'Example'})
        self.assertEqual(result['matches'][0]['console'],'NES')
        self.assertFalse(rom.IMPORTS.exists())

    def test_region_ranking_keeps_filename_region_even_when_query_is_shortened(self):
        europe={'name':'Example (Europe)', 'developer':'Wrong', 'releaseyear':1991}
        with patch('rom_import.catalog',return_value=[europe,self.entry]):
            result=rom.search({**self.request,'query':'Example'})
            self.assertEqual(result['matches'][0]['title'],'Example (USA)')
            self.assertFalse(result['matches'][0]['regionMismatch'])
            self.assertTrue(result['matches'][1]['regionMismatch'])
            with self.assertRaisesRegex(ValueError,'selected region'):
                rom.prepare({**self.request,'match':'Example (Europe)'})
            self.assertFalse(rom.IMPORTS.exists())
            result=rom.prepare({**self.request,'match':'Example (Europe)','confirmRegionMismatch':True})
            self.assertEqual(result['details']['catalogTitle'],'Example (Europe)')

    def test_file_browser_filters_extensions_hides_dotfiles_and_paginates(self):
        root=self.path.parent
        (root/'Folder').mkdir();(root/'wrong.iso').touch();(root/'.hidden.nes').touch()
        for i in range(110):(root/f'Game {i:03}.nes').touch()
        result=rom.browse({'system':'nes','path':str(root)})
        names=[e['name'] for e in result['entries']]
        self.assertNotIn('wrong.iso',names);self.assertNotIn('.hidden.nes',names)
        self.assertTrue(result['entries'][0]['directory'])
        self.assertEqual(len(result['entries']),100)
        more=rom.browse({'system':'nes','path':str(root),'offset':100})
        self.assertTrue(more['entries']);self.assertFalse(set(names)&{e['name'] for e in more['entries']})

    def test_background_uses_same_region_gameplay_and_exposes_all_asset_types(self):
        portrait=self.path.parent/'p.png';portrait.write_bytes(b'portrait')
        urls=[]
        def fetch(url,path):urls.append(url);path.write_bytes(b'gameplay');return True
        game={'slug':'example','thumb':'Nintendo_-_Nintendo_Entertainment_System/Example (USA)'}
        with patch('games.artwork',return_value={'p':portrait, '_logo':portrait, '':portrait}),patch('games.fetch',side_effect=fetch):
            assets,warning=rom.import_artwork(game)
        self.assertEqual([a['type'] for a in assets],[0,1,2,3]);self.assertEqual(warning,'')
        self.assertIn('/Named_Snaps/Example%20%28USA%29.png',urls[0])
        self.assertNotIn('Named_Titles',urls[0])

    def test_curated_hero_is_preserved_and_missing_art_is_reported(self):
        from PIL import Image
        hero=self.path.parent/'hero.jpg';Image.new('RGB',(100,30),'blue').save(hero)
        game={'slug':'example','thumb':'Console/Example (USA)'}
        (games.ART / game['slug']).mkdir(parents=True)
        with patch('games.artwork',return_value={'_hero':hero}),patch('games.fetch') as fetch:
            assets,warning=rom.import_artwork(game)
            fetch.assert_not_called()
        self.assertEqual(assets[0]['type'],1);self.assertEqual(assets[0]['extension'],'jpg')
        self.assertIn('Box art',warning)

    def test_unrecorded_shortcut_cannot_be_marked_complete(self):
        prepared=rom.prepare(self.request)
        with self.assertRaisesRegex(ValueError,'does not match'):
            rom.finish({'slug':prepared['slug'],'appid':42})
        self.assertFalse(rom.DETAILS.exists())

    def test_finish_rejects_invalid_or_unknown_id(self):
        for appid in [0,-1,2**32,True]:
            with self.assertRaises(ValueError): rom.finish({'slug':'none','appid':appid})
        with self.assertRaisesRegex(ValueError,'Import not found'): rom.finish({'slug':'none','appid':42})


if __name__ == '__main__': unittest.main()
