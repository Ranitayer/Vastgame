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
    def test_failed_backup_clears_only_ordinary_marker(self):
        for final in (False, True):
            for failure in ('close', 'upload', 'receipt'):
                with self.subTest(final=final, failure=failure), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp); profile = root/'profiles/fixture'; profile.mkdir(parents=True)
                    (profile/'manifest.json').write_text(json.dumps({'id': 'fixture'}))
                    marker = root/'stopping'
                    receipt = root/'receipt'; receipt.mkdir()
                    def mapped(value, *args):
                        if str(value) == '/var/lib/vast-gaming/status/stopping': value = marker
                        return Path(value, *args)
                    args = ['game_state.py', 'backup', 'fixture', '--root', str(root),
                            '--cache-key', 'a'*64, '--receipt', str(receipt)] + (['--final'] if final else [])
                    with patch.object(sys, 'argv', args), patch.object(state, 'Path', side_effect=mapped), \
                         patch.object(state, 'stop_cleanly', side_effect=OSError('close failed') if failure == 'close' else None), \
                         patch.object(state, 'backup', side_effect=OSError('upload failed') if failure == 'upload' else None, return_value={'snapshot': 'verified'}), \
                         patch.object(state, 'Remote'), patch.object(state, 'idle'):
                        with self.assertRaises(OSError): state.main()
                    self.assertEqual(marker.exists(), final)

    def test_ordinary_backup_cannot_remove_prior_final_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root/'profiles/fixture'; profile.mkdir(parents=True)
            (profile/'manifest.json').write_text('{"id":"fixture"}')
            marker = root/'stopping'; marker.touch()
            def mapped(value, *args):
                return Path(marker if str(value) == '/var/lib/vast-gaming/status/stopping' else value, *args)
            args = ['game_state.py', 'backup', 'fixture', '--root', str(root)]
            with patch.object(sys, 'argv', args), patch.object(state, 'Path', side_effect=mapped), \
                 patch.object(state, 'stop_cleanly') as close:
                with self.assertRaisesRegex(RuntimeError, 'state resume'): state.main()
                close.assert_not_called()
            self.assertTrue(marker.exists())

    def test_explicit_resume_clears_marker_without_backup_or_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root/'profiles/fixture'; profile.mkdir(parents=True)
            (profile/'manifest.json').write_text('{"id":"fixture"}')
            marker = root/'stopping'; marker.touch()
            def mapped(value, *args):
                return Path(marker if str(value) == '/var/lib/vast-gaming/status/stopping' else value, *args)
            args = ['game_state.py', 'resume', 'fixture', '--root', str(root)]
            with patch.object(sys, 'argv', args), patch.object(state, 'Path', side_effect=mapped), \
                 patch.object(state, 'Remote') as remote, patch.object(state, 'stop_cleanly') as close:
                state.main()
                remote.assert_not_called(); close.assert_not_called()
            self.assertFalse(marker.exists())

    def test_changed_guest_manifest_is_rejected_before_closing_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root/'profiles/fixture'; profile.mkdir(parents=True)
            (profile/'manifest.json').write_text('{"id":"fixture"}')
            args = ['game_state.py', 'backup', 'fixture', '--root', str(root), '--manifest-sha', '0'*64]
            with patch.object(sys, 'argv', args), patch.object(state, 'stop_cleanly') as close:
                with self.assertRaisesRegex(ValueError, 'save policy changed'): state.main()
                close.assert_not_called()

    def test_container_probe_uses_the_matching_helper_without_file_changes(self):
        with patch.object(state.subprocess, 'run') as run:
            state.container_state('container', 'idle', 'fixture')
        self.assertEqual(run.call_args.args[0], ['docker', 'exec', '-i', 'container', 'python3', '-', 'idle', 'fixture'])
        self.assertEqual(run.call_args.kwargs['input'], Path(state.__file__).read_bytes())

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

    def test_launch_waits_for_checkpoint_without_bypassing_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.lock'; messages=[]
            with path.open('a') as owner, path.open('a') as launch:
                fcntl.flock(owner,fcntl.LOCK_EX)
                def release(delay): fcntl.flock(owner,fcntl.LOCK_UN)
                with patch.object(state.time,'sleep',side_effect=release):
                    state.wait_for_state_lock(launch, timeout=1, mode=fcntl.LOCK_SH, report=messages.append)
                self.assertEqual(len(messages),1)
                with path.open('a') as contender:
                    with self.assertRaises(BlockingIOError): fcntl.flock(contender,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def test_launch_refuses_final_backup_even_if_lock_is_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/'stopping'; marker.touch()
            with (Path(tmp)/'state.lock').open('a') as launch:
                with self.assertRaisesRegex(RuntimeError,'Final backup'):
                    state.wait_for_state_lock(launch, mode=fcntl.LOCK_SH, stopping=marker)

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
