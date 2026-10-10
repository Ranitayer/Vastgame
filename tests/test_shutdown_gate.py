import fcntl
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('shutdown_gate', Path(__file__).resolve().parents[1]/'src/runtime/shutdown_gate.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ShutdownGateTests(unittest.TestCase):
    def fixture(self, folder):
        root, profiles = Path(folder)/'status', Path(folder)/'profiles'
        root.mkdir(); profiles.mkdir()
        (root/'instance-label').write_text('vastgame-123')
        return root, profiles

    def test_unused_game_is_frozen_before_returning_permission_to_skip_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, profiles = self.fixture(temporary)
            (root/'launch-guard-v1').touch()
            self.assertEqual(module.freeze('vastgame-123', 'fixture', root, profiles), 'unstarted')
            self.assertTrue((root/'stopping').exists())
            (root/'game-started').touch()
            self.assertEqual(module.freeze('vastgame-123', 'fixture', root, profiles), 'started')

    def test_old_runtime_and_other_vm_identity_never_authorize_skipping_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, profiles = self.fixture(temporary)
            self.assertEqual(module.freeze('vastgame-123', 'fixture', root, profiles), 'unknown')
            self.assertFalse((root/'stopping').exists())
            with self.assertRaises(ValueError): module.freeze('vastgame-999', 'fixture', root, profiles)

    def test_active_launch_prevents_a_false_unstarted_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, profiles = self.fixture(temporary)
            (root/'launch-guard-v1').touch()
            (profiles/'fixture').mkdir()
            with (profiles/'fixture/state.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                with self.assertRaises(BlockingIOError): module.freeze('vastgame-123', 'fixture', root, profiles)
                self.assertFalse((root/'stopping').exists())

    def test_cli_uses_guest_identity_and_can_cancel_during_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, profiles = self.fixture(temporary)
            (root/'game-id').write_text('fixture')
            (root/'bootstrap-launch-guard-v1').touch()
            self.assertEqual(module.freeze('vastgame-123', root=root, profiles=profiles), 'unstarted')
            self.assertTrue((root/'stopping').exists())
            (root/'game-started').touch()
            self.assertEqual(module.freeze('vastgame-123', root=root, profiles=profiles), 'started')
            with self.assertRaises(ValueError): module.freeze('vastgame-123', 'other', root, profiles)

    def test_cli_old_runtime_without_activity_evidence_is_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, profiles = self.fixture(temporary)
            (root/'session.json').write_text('{"game_id":"fixture"}')
            self.assertEqual(module.freeze('vastgame-123', root=root, profiles=profiles), 'unknown')
            self.assertFalse((root/'stopping').exists())
