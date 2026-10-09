"""Focused metadata tests; network responses are replaced with fixtures."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('game_details', Path(__file__).resolve().parents[1] / 'src/client/game_details.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GameDetailsTests(unittest.TestCase):
    def test_cached_details_do_not_download(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            value = {'description': 'Game', 'developers': [], 'publishers': [], 'reviews': None}
            (cache / '1.json').write_text(json.dumps({'updated': time.time(), 'details': value}))
            with patch.object(module, 'fetch', side_effect=AssertionError('Unexpected network')):
                self.assertEqual(module.details(1, cache), value)

    def test_metadata_is_plain_text_and_review_counts_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            responses = [{'1': {'success': True, 'data': {'short_description': '<b>Hello</b> &amp; world', 'developers': ['<i>Studio</i>'], 'publishers': []}}},
                         {'success': 1, 'query_summary': {'total_reviews': 10, 'total_positive': 11, 'review_score_desc': 'Positive'}}]
            with patch.object(module, 'fetch', side_effect=responses):
                result = module.details(1, Path(directory))
            self.assertEqual(result['description'], 'Hello & world')
            self.assertEqual(result['developers'], ['Studio'])
            self.assertIsNone(result['reviews'])
            self.assertFalse((Path(directory) / '1.json').exists())

    def test_invalid_identifier_cannot_fetch_or_write(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(module, 'fetch', side_effect=AssertionError('Unexpected network')):
                with self.assertRaises(ValueError):
                    module.details('../secret', Path(directory))
