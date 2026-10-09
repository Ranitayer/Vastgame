import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/client'))
import game_identity as identity


class GameIdentityTests(unittest.TestCase):
    def test_known_games_need_no_local_presentation_or_network(self):
        fixtures = [('cyberpunk', 'Cyberpunk 2077', 'bin/x64/Cyberpunk2077.exe', 1091500),
                    ('expedition-33', 'Expedition 33', 'Expedition33_Steam.exe', 1903340),
                    ('fatekeeper', 'SLASHER-Win64-Shipping', 'SLASHER/Binaries/Win64/SLASHER-Win64-Shipping.exe', 2186990),
                    ('pragmata', 'PRAGMATA', 'PRAGMATA.exe', 3357650),
                    ('resident-evil', 're9', 're9.exe', 3764200),
                    ('still', 'Still Wakes the Deep', 'Habitat/Binaries/Win64/StillWakesTheDeep.exe', 1622910)]
        with tempfile.TemporaryDirectory() as temporary, patch.object(identity.urllib.request, 'urlopen', side_effect=AssertionError('Network used')):
            for gid, name, executable, appid in fixtures:
                manifest = dict(id=gid, name=name, game=dict(executable=executable))
                original = json.dumps(manifest)
                self.assertEqual(identity.resolve(manifest, cache=Path(temporary))['steam_appid'], appid)
                self.assertEqual(json.dumps(manifest), original)

    def test_manual_identity_takes_priority(self):
        manifest = dict(id='fixture', name='Fixture', steam={'id': 10})
        self.assertEqual(identity.resolve(manifest, dict(name='Custom name', steam_appid=20)), dict(name='Custom name', steam_appid=20))

    def test_unknown_title_is_searched_and_cached_for_future_offline_use(self):
        manifest = dict(id='brand-new-game', name='Brand New Game', game=dict(executable='Game.exe'))
        response = dict(items=[dict(type='app', id=123456, name='Brand New Game'), dict(type='app', id=99, name='Brand New Game Soundtrack')])
        with tempfile.TemporaryDirectory() as temporary, patch.object(identity, 'title_index', return_value={}):
            cache = Path(temporary)
            with patch.object(identity.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as fetch:
                result = identity.resolve(manifest, online=True, cache=cache)
                self.assertEqual(result['steam_appid'], 123456)
                self.assertEqual(fetch.call_count, 1)
            with patch.object(identity.urllib.request, 'urlopen', side_effect=AssertionError('Network used')):
                self.assertEqual(identity.resolve(manifest, online=True, cache=cache), result)

    def test_ambiguous_search_is_not_guessed_or_cached(self):
        manifest = dict(id='fixture', name='Fixture')
        response = dict(items=[dict(type='app', id=i, name='Fixture') for i in (1, 2)])
        with tempfile.TemporaryDirectory() as temporary, patch.object(identity, 'title_index', return_value={}), patch.object(identity.urllib.request, 'urlopen', side_effect=lambda *args, **kwargs: io.BytesIO(json.dumps(response).encode())):
            cache = Path(temporary)
            self.assertIsNone(identity.resolve(manifest, online=True, cache=cache)['steam_appid'])
            self.assertEqual(list(cache.iterdir()), [])

    def test_game_request_cannot_escape_the_library(self):
        with self.assertRaises(ValueError): identity.for_game('../private', Path('/unused'))
