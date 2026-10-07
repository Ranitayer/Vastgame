import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/runtime'))
import game_state as state
import test_game_state as fixtures


class StateLockTests(unittest.TestCase):
    def waiter(self, path, timeout):
        script = '''
import sys
from game_state import wait_for_state_lock
with open(sys.argv[1], 'a') as lock:
    wait_for_state_lock(lock, float(sys.argv[2]))
    print('LOCK_ACQUIRED', flush=True)
'''
        return subprocess.Popen([sys.executable, '-c', script, str(path), str(timeout)],
            env=dict(os.environ, PYTHONPATH=str(ROOT/'src/runtime')), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)

    def test_shared_and_exclusive_contention_waits_then_succeeds(self):
        for mode in (fcntl.LOCK_SH, fcntl.LOCK_EX):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'state.lock'
                with path.open('a') as owner:
                    fcntl.flock(owner, mode)
                    child=self.waiter(path, 2)
                    try:
                        line=child.stdout.readline()
                        self.assertIn('Waiting for active', line)
                        self.assertIsNone(child.poll())
                        fcntl.flock(owner, fcntl.LOCK_UN)
                        out, err=child.communicate(timeout=3)
                        self.assertEqual(child.returncode, 0, err)
                        self.assertIn('LOCK_ACQUIRED', out)
                    finally:
                        if child.poll() is None: child.kill()
                        child.communicate()

    def test_busy_lock_times_out_without_unlinking_or_unlocking_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.lock'
            with path.open('a') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX)
                inode=path.stat().st_ino
                child=self.waiter(path, 0.1)
                out, err=child.communicate(timeout=3)
                self.assertNotEqual(child.returncode, 0)
                self.assertIn('State lock still busy after 0.1s', err)
                self.assertIn('VM retained', err)
                self.assertNotIn('LOCK_ACQUIRED', out)
                self.assertEqual(path.stat().st_ino, inode)
                with path.open('a') as contender:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_backup_waits_before_closing_game_and_committing_receipt(self):
        fixture=fixtures.StateTests(); fixture.setUp()
        try:
            profile=fixture.root/'profiles/fixture'; profile.mkdir(parents=True)
            (profile/'manifest.json').write_text(json.dumps(fixture.m))
            marker=fixture.root/'status/stopping'; marker.parent.mkdir()
            receipt=profile/'receipt.json'
            def mapped(value, *args):
                if str(value)=='/var/lib/vast-gaming/status/stopping': value=marker
                return Path(value,*args)
            with (profile/'state.lock').open('a') as owner:
                fcntl.flock(owner,fcntl.LOCK_SH)
                def release(delay):
                    self.assertFalse(marker.exists())
                    self.assertFalse(receipt.exists())
                    self.assertEqual(fixture.remote.uploads, [])
                    fcntl.flock(owner,fcntl.LOCK_UN)
                def stopped(gid):
                    self.assertTrue(marker.exists())
                    with (profile/'state.lock').open('a') as contender:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(contender,fcntl.LOCK_EX | fcntl.LOCK_NB)
                args=['game_state.py','backup','fixture','--root',str(fixture.root),
                      '--instance','123','--cache-key','a'*64,'--final','--receipt',str(receipt)]
                with patch.object(sys,'argv',args), patch.object(state,'Path',side_effect=mapped), \
                     patch.object(state.time,'sleep',side_effect=release), \
                     patch.object(state,'stop_cleanly',side_effect=stopped) as close, \
                     patch.object(state,'idle'), patch.object(state,'Remote',return_value=fixture.remote):
                    state.main()
                close.assert_called_once_with('fixture')
            self.assertEqual(json.loads(receipt.read_text())['instance_id'],'123')
            self.assertTrue(marker.exists())
            self.assertTrue(fixture.remote.uploads[-1].endswith('COMMITTED.json'))
        finally:
            fixture.tmp.cleanup()


if __name__=='__main__': unittest.main()
