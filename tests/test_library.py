import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/client'))
spec = importlib.util.spec_from_file_location('library_catalog', ROOT/'src/client/game_catalog.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LibrarySummaryTests(unittest.TestCase):
    def test_existing_catalog_is_sanitized_and_broken_entries_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root/'games'
            game = catalog/'portal'
            game.mkdir(parents=True)
            manifest = dict(id='portal', name='Portal', version='v1',
                source={'path': '/private/source'}, environment={'SECRET': 'private'},
                game={'arguments': ['private']}, runner={'version': 'ge-proton'},
                package={'size': 1024, 'unpacked_bytes': 2048, 'sha256': 'a'*64})
            path = game/'manifest.json'
            path.write_text(json.dumps(manifest))
            selected = root/'selected'
            selected.write_text('portal')
            (root/'library.json').write_text(json.dumps({'games': {'portal': {'name': 'Portal display title', 'steam_appid': 400}}}))
            broken = catalog/'broken'
            broken.mkdir()
            (broken/'manifest.json').write_text('{')
            result = module.library_summary(catalog, selected)
            self.assertEqual(result['skipped'], 1)
            self.assertEqual(len(result['games']), 1)
            summary = result['games'][0]
            self.assertTrue(summary['selected'])
            self.assertTrue(summary['packaged'])
            self.assertEqual(summary['download_bytes'], 1024)
            self.assertEqual(summary['name'], 'Portal display title')
            self.assertEqual(summary['steam_appid'], 400)
            self.assertNotIn('private', json.dumps(result))
            self.assertEqual(json.loads(path.read_text()), manifest)

    def test_missing_catalog_is_empty_without_creating_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(module.library_summary(root/'games', root/'selected'), {'games': [], 'skipped': 0})
            self.assertFalse((root/'games').exists())

    def test_new_pc_resolves_ids_without_library_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root/'games/re9'
            game.mkdir(parents=True)
            manifest = dict(id='re9', name='re9', game=dict(executable='re9.exe'))
            path = game/'manifest.json'
            path.write_text(json.dumps(manifest))
            summary = module.library_summary(root/'games', root/'selected')['games'][0]
            self.assertEqual(summary['steam_appid'], 3764200)
            self.assertEqual(summary['name'], 'Resident Evil Requiem')
            self.assertFalse((root/'library.json').exists())
            self.assertEqual(json.loads(path.read_text()), manifest)
