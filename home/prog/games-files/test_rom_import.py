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
        for target, value in [('shutil.which','/test/emulator'), ('games.artwork',{}), ('rom_import.catalog',[self.entry])]:
            p=patch(target,return_value=value); p.start(); self.addCleanup(p.stop)

    def test_prepare_finish_retry_preserves_metadata_and_manifest(self):
        games.MANIFEST.write_text(json.dumps({'games':[], 'extraSaves':[{'name':'keep'}]}))
        before=games.MANIFEST.read_bytes()
        rom.atomic_json(rom.DETAILS, {'42':{'developer':'Unrelated'}})
        first=rom.prepare(self.request)
        self.assertEqual(first['details']['controllerSupport'],'emulated')
        rom.finish({'slug':first['slug'],'appid':2147483650})
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

    def test_finish_rejects_invalid_or_unknown_id(self):
        for appid in [0,-1,2**32,True]:
            with self.assertRaises(ValueError): rom.finish({'slug':'none','appid':appid})
        with self.assertRaisesRegex(ValueError,'Import not found'): rom.finish({'slug':'none','appid':42})


if __name__ == '__main__': unittest.main()
