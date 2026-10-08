import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cleanup', ROOT/'src/client/cleanup.py')
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class CleanupTests(unittest.TestCase):
    def test_empty_preview_does_not_inspect_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(cleanup, 'activity', side_effect=PermissionError) as scan:
                cleanup.cleanup(root/'app', root/'state', root/'data')
            scan.assert_not_called()

    def test_unreadable_process_keeps_candidate_without_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.old(root/'state/state.test', time.time()-2*cleanup.DAY)
            with patch.object(cleanup, 'activity', return_value=[('123', None)]):
                cleanup.cleanup(root/'app', root/'state', root/'data', apply=True)
            self.assertTrue(path.exists())

    def old(self, path, timestamp):
        path.mkdir(parents=True, exist_ok=True)
        os.utime(path, (timestamp, timestamp))
        return path

    def test_retention_protects_recent_and_current_reports_and_unknown_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root/'state'; data = root/'data'; app = root/'app'
            now = time.time()
            for i in range(13):
                self.old(state/f'hud.{i:02}', now-(30-i)*cleanup.DAY)
                self.old(state/'reports'/str(100+i), now-(30-i)*cleanup.DAY)
            (state/'latest-report').write_text(str(state/'reports/100'))
            (state/'instance_id').write_text('101')
            self.old(state/'hud.fresh', now)
            self.old(state/'backups/game', now-100*cleanup.DAY)
            self.old(data/'app', now-100*cleanup.DAY)
            chosen = {p for p, _ in cleanup.candidates(app, state, data, now)}
            self.assertNotIn(state/'reports/100', chosen)
            self.assertNotIn(state/'reports/101', chosen)
            self.assertNotIn(state/'hud.fresh', chosen)
            self.assertNotIn(state/'backups/game', chosen)
            self.assertNotIn(data/'app', chosen)
            self.assertIn(state/'reports/102', chosen)

    def test_only_old_valid_windows_backends_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); now = time.time()
            for i in range(3):
                path = root/f'app-backup.{i}'
                (path/'bin').mkdir(parents=True); (path/'bin/vastgame').touch()
                (path/'src/manager').mkdir(parents=True); (path/'src/manager/commands.sh').touch()
                for item in [*path.rglob('*'), path]:
                    os.utime(item, (now-(10-i)*cleanup.DAY,)*2)
            unknown = self.old(root/'app-backup.unknown', now-30*cleanup.DAY)
            chosen = {p for p, _ in cleanup.candidates(root/'app', root/'state', root, now)}
            self.assertEqual(chosen, {root/'app-backup.0', root/'app-backup.1'})
            self.assertNotIn(unknown, chosen)

    def test_symlink_parent_and_process_reference_prevent_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); outside = root/'outside'; outside.mkdir()
            (root/'reports').symlink_to(outside, target_is_directory=True)
            self.assertEqual(cleanup.directories(root/'reports', '*'), [])
            self.assertTrue(cleanup.active(root/'hud.test', [('123', 'VASTGAME_HUD_DIR='+str(root/'hud.test'))]))

    def test_preview_does_not_remove_and_apply_skips_active_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root/'state'; app = root/'app'; data = root/'data'
            path = self.old(state/'state.test', time.time()-2*cleanup.DAY)
            with patch.object(cleanup, 'activity', return_value=[]):
                cleanup.cleanup(app, state, data)
            self.assertTrue(path.exists())
            with patch.object(cleanup, 'activity', return_value=[('123', str(path))]):
                cleanup.cleanup(app, state, data, apply=True)
            self.assertTrue(path.exists())

    def test_active_build_lock_blocks_apply(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root/'state'; state.mkdir()
            with (state/'build.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with self.assertRaisesRegex(RuntimeError, 'active'):
                    cleanup.cleanup(root/'app', state, root/'data', apply=True)
