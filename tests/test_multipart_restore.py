import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/runtime'))
import multipart_restore as restore


class MultipartRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original_path = os.environ['PATH']
        self.games = self.root / 'games'
        self.source = self.root / 'source'; self.source.mkdir()
        self.original = os.urandom(2 * 1024 * 1024)
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as tar:
            for name, contents in [('Game.exe', b'executable'), ('data.bin', self.original)]:
                info = tarfile.TarInfo(name); info.size = len(contents)
                tar.addfile(info, io.BytesIO(contents))
        archive = subprocess.run(['zstd', '-q', '-1', '-c'], input=buffer.getvalue(), capture_output=True, check=True).stdout
        self.sha = hashlib.sha256(archive).hexdigest()
        parts = []
        for index, offset in enumerate(range(0, len(archive), 128 * 1024)):
            data = archive[offset:offset + 128 * 1024]
            name = f'part-{index:05d}'
            (self.source / name).write_bytes(data)
            parts.append(dict(name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()))
        self.manifest = dict(schema=1, id='fixture', game=dict(executable='Game.exe', working_dir=''),
                             package=dict(size=len(archive), parts=parts))
        fake = self.root / 'rclone'
        fake.write_text('''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
name = sys.argv[2].rsplit('/', 1)[-1]
if os.environ.get('WAIT_FOR_EXTRACTION') and int(name.split('-')[1]) >= 3:
    deadline = time.monotonic() + 8
    while not Path(os.environ['WAIT_FOR_EXTRACTION']).is_file():
        if time.monotonic() > deadline:
            sys.exit('Extraction did not overlap downloads')
        time.sleep(0.02)
if name == 'part-00000':
    time.sleep(0.05)  # Later parts arrive first.
sys.stdout.buffer.write((Path(os.environ['PARTS_SOURCE']) / name).read_bytes())
''')
        fake.chmod(0o755)
        self.env = patch.dict(os.environ, PATH=str(self.root) + ':' + os.environ['PATH'], PARTS_SOURCE=str(self.source))
        self.env.start(); self.addCleanup(self.env.stop)

    def run_restore(self, sha=None):
        restore.restore(self.manifest, sha or self.sha, self.games, 'remote/parts',
                        status=self.root/'game.json', workers=3)

    def test_completed_restore_preserves_measured_identity_and_throughput(self):
        with patch.dict(os.environ, VASTGAME_MACHINE_ID='456', VASTGAME_LAUNCH_LABEL='vastgame-123'):
            self.run_restore()
        record = json.loads((self.root/'game.json').read_text())
        self.assertEqual(record['machine_id'], '456')
        self.assertEqual(record['launch_label'], 'vastgame-123')
        self.assertGreater(record['restore_mbps'], 0)
        self.assertEqual(record['state'], 'done')

    def existing(self):
        target = self.games/'fixture'; target.mkdir(parents=True)
        (target/'old-save-proof').write_text('preserve')

    def test_extraction_overlaps_downloads_and_out_of_order_parts_are_ordered(self):
        with patch.dict(os.environ, WAIT_FOR_EXTRACTION=str(self.games/'fixture.installing/Game.exe')):
            self.run_restore()
        self.assertEqual((self.games/'fixture/data.bin').read_bytes(), self.original)
        data = json.loads((self.root/'game.json').read_text())
        self.assertEqual(data['state'], 'done')
        self.assertEqual(data['verified_parts'], len(self.manifest['package']['parts']))
        self.assertEqual(data['bytes'], data['total'])
        self.assertEqual(data['streamed_bytes'], data['total'])
        self.assertFalse(list(self.games.glob('.parts-*')))

    def test_corrupt_part_rejected_and_old_installation_preserved(self):
        self.existing()
        path = self.source/'part-00001'
        path.write_bytes(b'x' * path.stat().st_size)
        with self.assertRaisesRegex(RuntimeError, 'part-00001'):
            self.run_restore()
        self.assertEqual((self.games/'fixture/old-save-proof').read_text(), 'preserve')
        self.assertEqual(json.loads((self.root/'game.json').read_text())['state'], 'error')

    def test_whole_archive_checksum_required_before_publish(self):
        self.existing()
        with self.assertRaisesRegex(RuntimeError, 'Whole archive checksum'):
            self.run_restore('0' * 64)
        self.assertTrue((self.games/'fixture/old-save-proof').exists())

    def test_missing_exact_executable_does_not_publish(self):
        self.existing()
        self.manifest['game']['executable'] = 'missing.exe'
        with self.assertRaisesRegex(ValueError, 'executable missing'):
            self.run_restore()
        self.assertTrue((self.games/'fixture/old-save-proof').exists())

    def test_short_download_is_rejected(self):
        (self.source/'part-00000').write_bytes(b'truncated')
        with self.assertRaisesRegex(RuntimeError, 'part-00000'):
            self.run_restore()
        self.assertFalse((self.games/'fixture').exists())

    def test_invalid_part_order_rejected_before_download(self):
        self.manifest['package']['parts'].reverse()
        with self.assertRaisesRegex(ValueError, 'consecutive'):
            self.run_restore()
        self.assertFalse(self.games.exists())

    def test_real_rclone_local_transport_restores_the_exact_package(self):
        with patch.dict(os.environ, PATH=self.original_path):
            restore.restore(self.manifest, self.sha, self.games, str(self.source), workers=3)
        self.assertEqual((self.games/'fixture/data.bin').read_bytes(), self.original)

    def test_unusable_working_directory_preserves_old_installation(self):
        self.existing()
        self.manifest['game']['working_dir'] = 'missing-folder'
        with self.assertRaisesRegex(ValueError, 'working directory missing'):
            self.run_restore()
        self.assertTrue((self.games/'fixture/old-save-proof').exists())

    def test_interrupted_publication_recovers_previous_installation(self):
        self.existing()
        (self.games/'fixture').rename(self.games/'fixture.previous')
        self.manifest['game']['executable'] = 'missing.exe'
        with self.assertRaises(ValueError):
            self.run_restore()
        self.assertTrue((self.games/'fixture/old-save-proof').exists())

    def test_bootstrap_prepares_before_waiting_for_game_and_restores_state_after(self):
        boot = (Path(__file__).resolve().parents[1]/'src/bootstrap/start.sh').read_text()
        start = boot.index('wait "$GOW_PID"')
        prepare = boot.index('  prepare_game_environment\n', start)
        join = boot.index('wait "$GAME_PID"', start)
        state = boot.index('python3 /opt/vastgame/game_state.py restore', start)
        self.assertLess(start, prepare); self.assertLess(prepare, join); self.assertLess(join, state)
        self.assertIn('/opt/vastgame/multipart_restore.py', boot)


if __name__ == '__main__':
    unittest.main()
