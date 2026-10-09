import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('artwork', ROOT/'src/client/game_artwork.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ArtworkTests(unittest.TestCase):
    def test_cached_image_needs_no_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            (cache/'400-cover.image').write_bytes(b'\xff\xd8\xffcached-image')
            with patch.object(module.urllib.request, 'urlopen', side_effect=AssertionError('Network used')):
                result = module.artwork(400, 'cover', cache)
            self.assertTrue(result['image'].startswith('data:image/jpeg;base64,'))

    def test_invalid_requests_cannot_select_paths_or_urls(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)/'cache'
            for appid, kind in (('../private', 'cover'), (400, '../banner'), (0, 'cover')):
                with self.assertRaises(ValueError):
                    module.artwork(appid, kind, cache)
            self.assertFalse(cache.exists())
