import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/client'))
spec = importlib.util.spec_from_file_location('offer_quote', ROOT / 'src/client/offer_quote.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class OfferQuoteTests(unittest.TestCase):
    def offer(self, **changes):
        return dict(dict(id=42, machine_id=99, num_gpus=1, rentable=True, vms_enabled=True,
                         gpu_arch='nvidia', gpu_ram=8192, cpu_cores_effective=4,
                         direct_port_count=1, disk_space=200, dph_total=0.25), **changes)

    def test_disk_and_price_failures_are_distinct_and_include_actual_numbers(self):
        for offer, disk, approved, code in ((self.offer(), 250, None, 'DISK_INSUFFICIENT'),
                                            (self.offer(), 150, 0.20, 'PRICE_INCREASED')):
            with self.subTest(code=code), self.assertRaises(module.OfferError) as caught:
                module.validate(offer, disk, approved)
            self.assertEqual(caught.exception.error['code'], code)
        self.assertEqual(module.validate(self.offer(), 150, 0.25)['disk_gb'], 150)

    def test_lookup_matches_returned_id_without_provider_id_filter_or_fallback(self):
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps([self.offer(id=41), self.offer()]), stderr='')
        with patch.object(module.subprocess, 'run', return_value=result) as run:
            self.assertEqual(module.fetch(42, 150, 99)['id'], 42)
            args = run.call_args.args[0]
            self.assertNotIn(' id=', args[3])
            self.assertIn('machine_id=99', args[3])
            self.assertEqual(args[args.index('--storage') + 1], '150')
            with self.assertRaises(module.OfferError) as missing: module.fetch(43, 150, 99)
            self.assertEqual(missing.exception.error['code'], 'OFFER_UNAVAILABLE')

    def test_timeout_is_not_reported_as_an_unavailable_rig(self):
        with patch.object(module.subprocess, 'run', side_effect=subprocess.TimeoutExpired('vastai', 60)):
            with self.assertRaises(module.OfferError) as caught: module.fetch(42, 150)
            self.assertEqual(caught.exception.error['code'], 'API_TIMEOUT')
