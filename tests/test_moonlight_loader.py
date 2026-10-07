import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MoonlightLoaderTests(unittest.TestCase):
    def run_listing(self, native_error, flatpak_installed=True):
        source = (ROOT/'src/manager/client.sh').read_text()
        start = source.index('    set +e', source.index('echo "Checking Moonlight pairing..."'))
        end = source.index('    ok "Moonlight/Wolf pairing verified"', start)
        with tempfile.TemporaryDirectory() as tmp:
            code = '''set -Eeuo pipefail
warn() { echo "WARNING:$*"; }
CLIENT_DIR=/fixture
python3() { [[ "$1" == /fixture/moonlight_settings.py ]]; }
moonlight() { echo "$TEST_NATIVE_ERROR"; return 127; }
flatpak() {
    printf '%s\\n' "$*" >> "$TEST_CALLS"
    if [[ "$1" == info ]]; then [[ "$TEST_INSTALLED" == 1 ]]; return; fi
    printf 'Vastgame - still\\r\\n'
}
timeout() { shift; "$@"; }
nohup() { echo UNEXPECTED_RECOVERY; }
check() {
    local ip=100.97.99.78 list_out rc
    local -a ml=(moonlight)
''' + source[start:end] + '''
printf 'CLIENT:%s\\n' "${ml[*]}"
printf 'APPS:%s\\n' "$list_out"
}
check
'''
            calls=Path(tmp)/'calls'
            result=subprocess.run(['bash','-c',code],capture_output=True,text=True,
                env=dict(os.environ,TEST_NATIVE_ERROR=native_error,TEST_INSTALLED='1' if flatpak_installed else '0',
                         TEST_CALLS=str(calls),VASTGAME_WINDOWS='0'))
            return result, calls.read_text() if calls.exists() else ''

    def test_loader_failure_retries_installed_flatpak_and_normalizes_app_list(self):
        result,calls=self.run_listing('moonlight: symbol lookup error: libQt6Qml.so: undefined symbol')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('CLIENT:flatpak run com.moonlight_stream.Moonlight',result.stdout)
        self.assertIn('APPS:Vastgame - still',result.stdout)
        self.assertNotIn('\r',result.stdout)
        self.assertIn('list 100.97.99.78',calls)
        self.assertNotIn('pairing could not be verified',result.stdout)

    def test_missing_fallback_reports_local_failure_without_reopening_broken_client(self):
        result,calls=self.run_listing('moonlight: error while loading shared libraries: libQt6Qml.so',False)
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('cannot load its local libraries',result.stdout)
        self.assertNotIn('UNEXPECTED_RECOVERY',result.stdout)
        self.assertNotIn('list 100.97.99.78',calls)

    def test_pairing_failure_does_not_change_client_backend(self):
        result,calls=self.run_listing('Host is not paired')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('pairing could not be verified',result.stdout)
        self.assertEqual(calls,'')
