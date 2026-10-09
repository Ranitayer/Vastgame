import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('disk_capacity', Path(__file__).resolve().parents[1] / 'src/client/disk_capacity.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class DiskCapacityTests(unittest.TestCase):
    def test_runtime_reserve_and_minimum_are_included(self):
        self.assertEqual(module.required_disk_gb({'package': {'size': 1, 'unpacked_bytes': 1}}), 60)

    def test_multipart_restore_needs_only_eight_chunks_in_flight(self):
        package = {'size': 100 * 1024**3, 'unpacked_bytes': 120 * 1024**3, 'parts': [{'size': 1024**3}] * 100}
        streamed = module.required_disk_gb({'package': package})
        del package['parts']
        self.assertLess(streamed, module.required_disk_gb({'package': package}))

    def test_invalid_sizes_never_authorize_a_rental(self):
        for package in ({'size': True, 'unpacked_bytes': 1}, {'size': 1, 'unpacked_bytes': -1}, {'size': 1, 'unpacked_bytes': 1, 'parts': [{'size': -1}]}):
            with self.assertRaises(ValueError): module.required_disk_gb({'package': package})
