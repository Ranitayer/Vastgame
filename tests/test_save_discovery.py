import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_game_state import LocalRemote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/client'))
sys.path.insert(0, str(ROOT / 'src/runtime'))
import save_discovery as discovery
import game_state


class SaveDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = dict(id='still', name='STILL', game=dict(executable='Habitat/Binaries/Win64/Game.exe'), state=dict(saves=[]))
        self.game = dict(launch={'<base>/Habitat/Binaries/Win64/Game.exe': []}, files={
            '<winLocalAppData>/Habitat/Saved': dict(tags=['save'], when=[dict(os='windows')]),
            '<base>/config.ini': dict(tags=['config'])})
        self.catalog = dict(schema=1, sha256='fixture', games={'Still Wakes the Deep': self.game})

    def test_exact_executable_matches_title_and_expands_wine_users(self):
        found = discovery.discover(self.manifest, self.catalog)
        self.assertEqual(found['title'], 'Still Wakes the Deep')
        self.assertIn(dict(base='prefix', pattern='drive_c/users/*/AppData/Local/Habitat/Saved', kind='saves'), found['recipes'])

    def test_ambiguous_titles_are_not_guessed(self):
        self.catalog['games']['Another game'] = copy.deepcopy(self.game)
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            discovery.discover(self.manifest, self.catalog)
        self.assertEqual(discovery.discover(self.manifest, self.catalog, 'Still Wakes the Deep')['title'], 'Still Wakes the Deep')

    def test_no_fuzzy_matching(self):
        self.manifest['game']['executable'] = 'NotThatGame.exe'
        self.manifest['name'] = 'Still Wakes'
        self.assertIsNone(discovery.discover(self.manifest, self.catalog))

    def test_unresolved_store_registry_and_linux_paths_are_not_guessed(self):
        self.game['files']['<root>/userdata/<storeUserId>/123/remote'] = dict(tags=['save'], when=[dict(store='steam')])
        self.game['files']['<xdgData>/game'] = dict(tags=['save'], when=[dict(os='linux')])
        self.game['registry'] = {'HKEY_CURRENT_USER\\Software\\Game': {}}
        result = discovery.discover(self.manifest, self.catalog)
        self.assertEqual(len(result['recipes']), 2)
        self.assertEqual(len(result['unsupported']), 1)
        self.assertEqual(result['registry'], ['HKEY_CURRENT_USER\\Software\\Game'])

    def test_unsafe_patterns_rejected(self):
        for path in ('<base>/../outside', '<home>/../../secret', '<base>/**', '<base>/**/*', '<base>/./save', '<base>/file\x00'):
            self.assertIsNone(discovery.recipe(path), path)

    def test_generated_game_save_and_manual_required_path_both_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save = root / 'games/still/saves/slot.sav'
            save.parent.mkdir(parents=True); save.write_bytes(b'save outside prefix')
            self.manifest['state']['discovery'] = dict(recipes=[dict(base='game', pattern='saves/*.sav', kind='saves')])
            files = game_state.collect(self.manifest, root, 'saves')
            self.assertEqual(files['game/saves/slot.sav']['path'], save)
            self.manifest['state']['saves'] = [dict(base='game', path='missing.sav', required=True)]
            with self.assertRaisesRegex(ValueError, 'Required state path missing'):
                game_state.collect(self.manifest, root, 'saves')

    def test_discovered_game_directory_save_round_trips_verified_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'gaming'
            save = root / 'games/still/saves/slot.sav'
            save.parent.mkdir(parents=True); save.write_bytes(b'actual game-directory save')
            (root / 'games/still/Game.exe').write_bytes(b'never upload this')
            self.manifest['state']['discovery'] = dict(recipes=[dict(base='game', pattern='saves/*.sav', kind='saves')])
            remote_root = Path(tmp) / 'remote'; remote_root.mkdir()
            remote = LocalRemote(remote_root)
            record = game_state.backup(self.manifest, root, remote, 'fixture', 'cache')
            self.assertEqual(set(record['artifacts'][0]['files']), {'game/saves/slot.sav'})
            save.unlink()
            game_state.restore(self.manifest, root, remote, 'cache')
            self.assertEqual(save.read_bytes(), b'actual game-directory save')

    def test_discovery_never_follows_external_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = root / 'games/still'; base.mkdir(parents=True)
            outside = root / 'outside'; outside.mkdir(); (outside / 'slot.sav').write_bytes(b'private')
            (base / 'saves').symlink_to(outside)
            self.manifest['state']['discovery'] = dict(recipes=[dict(base='game', pattern='saves/*.sav', kind='saves')])
            with self.assertRaisesRegex(ValueError, 'escapes'):
                game_state.collect(self.manifest, root, 'saves')

    def test_cli_preserves_manual_state_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / 'manifest.json'
            self.manifest['state']['saves'] = ['drive_c/custom.sav']
            self.manifest['state']['shaders'] = ['shader.cache']
            manifest.write_text(json.dumps(self.manifest))
            with patch.object(sys, 'argv', ['save_discovery.py', str(manifest)]), patch.object(discovery, 'load', return_value=self.catalog), patch.object(Path, 'exists', return_value=True):
                discovery.main()
            updated = json.loads(manifest.read_text())
            self.assertEqual(updated['state']['saves'], ['drive_c/custom.sav'])
            self.assertEqual(updated['state']['shaders'], ['shader.cache'])


if __name__ == '__main__': unittest.main()
