from pathlib import Path
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/client'))
import crash_reports


class CrashReportTests(unittest.TestCase):
    def test_private_sessions_and_bounded_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'crashes'
            directory = crash_reports.prepare(root, 'game', 'session')
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            source = Path(tmp) / 'log'; source.write_bytes(b'a' * 200000 + b'end')
            crash_reports.log_tail(source, directory / 'moonlight.log')
            self.assertEqual((directory / 'moonlight.log').stat().st_size, 128 * 1024)
            self.assertTrue((directory / 'moonlight.log').read_bytes().endswith(b'end'))

    def test_retention_keeps_active_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = crash_reports.prepare(root, 'game', 'active')
            (active / 'pid').write_text(str(os.getpid()))
            for n in range(12): crash_reports.prepare(root, 'game', str(n))
            self.assertTrue(active.exists())
            self.assertLessEqual(len(list(root.glob('session-*'))), 11)

    def test_real_crashpad_creates_native_minidump(self):
        installed = Path.home() / '.local/share/vastgame/native/crashpad'
        library, handler = installed / 'vastgame_crashpad.so', installed / 'crashpad_handler'
        if not library.exists() or not handler.exists() or not shutil.which('g++'):
            self.skipTest('Built native Crashpad module required')
        with tempfile.TemporaryDirectory() as tmp:
            directory = crash_reports.prepare(Path(tmp) / 'crashes', 'fixture', 'fixture-session')
            source = Path(tmp) / 'probe.cpp'; source.write_text('#include <cstdlib>\nint main(){std::abort();}\n')
            probe = Path(tmp) / 'vastgame-crashpad-probe'
            subprocess.run(['g++', str(source), '-o', str(probe)], check=True, capture_output=True)
            environment = dict(os.environ, LD_PRELOAD=str(library), VASTGAME_CRASH_DIR=str(directory), VASTGAME_CRASH_HANDLER=str(handler))
            result = subprocess.run([str(probe)], env=environment, capture_output=True, timeout=15,
                                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
            self.assertNotEqual(result.returncode, 0)
            for _ in range(50):
                reports = list(directory.glob('pending/*.dmp')) + list(directory.glob('completed/*.dmp'))
                if reports: break
                time.sleep(.1)
            self.assertTrue(reports, result.stderr.decode())
            self.assertEqual(reports[0].read_bytes()[:4], b'MDMP')

    def test_native_moonlight_starts_normally_with_crashpad_and_hud(self):
        installed = Path.home() / '.local/share/vastgame/native'
        library, handler = installed / 'crashpad/vastgame_crashpad.so', installed / 'crashpad/crashpad_handler'
        moonlight = shutil.which('moonlight')
        if not library.exists() or not handler.exists() or not moonlight:
            self.skipTest('Native Moonlight and built Crashpad required')
        with tempfile.TemporaryDirectory() as tmp:
            directory = crash_reports.prepare(Path(tmp) / 'crashes', 'fixture', 'startup-test')
            preload = str(library)
            if (installed / 'moonlight_hud.so').exists():
                preload = str(installed / 'moonlight_hud.so') + ':' + preload
            result = subprocess.run([moonlight, '--help'], capture_output=True, timeout=15,
                                    env=dict(os.environ, LD_PRELOAD=preload, VASTGAME_CRASH_DIR=str(directory),
                                             VASTGAME_CRASH_HANDLER=str(handler), QT_QPA_PLATFORM='offscreen'))
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertTrue((directory / 'settings.dat').exists(), 'Crashpad did not initialize')
            self.assertFalse(list(directory.glob('pending/*.dmp')))


if __name__ == '__main__': unittest.main()
