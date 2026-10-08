"""Provider status transitions, without contacting Vast or starting a VM."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProviderStatesTests(unittest.TestCase):
    def check(self, commands):
        shell = f'''set -Eeuo pipefail
source "{ROOT}/src/manager/provider.sh"
extract_message() {{ jq -r '.status_msg // ""'; }}
destroy_failed_prompt() {{ echo "$2"; exit 77; }}
die() {{ echo "$*"; exit 78; }}
INSTANCE_FILE=/dev/null
listing='[]'
vastai() {{ echo "$listing"; }}
timeout() {{ shift; "$@"; }}
clock=100
date() {{ echo "$clock"; }}
offline='{{"id":123,"actual_status":"offline","intended_status":"running","next_state":"running"}}'
loading='{{"id":123,"actual_status":"loading","intended_status":"running"}}'
''' + commands
        return subprocess.run(['bash', '-c', shell], capture_output=True, text=True)

    def test_transient_offline_recovers_and_resets_grace(self):
        result = self.check('''check_instance_failure 123 "$offline"
clock=189; check_instance_failure 123 "$offline"
check_instance_failure 123 "$loading"
clock=200; check_instance_failure 123 "$offline"
clock=289; check_instance_failure 123 "$offline"
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_persistent_offline_fails_after_grace(self):
        result = self.check('''check_instance_failure 123 "$offline"
clock=190; check_instance_failure 123 "$offline"
''')
        self.assertEqual(result.returncode, 77)
        self.assertIn('remained offline for 90 seconds', result.stdout)

    def test_stop_request_is_not_hidden_by_offline_grace(self):
        result = self.check('''check_instance_failure 123 '{"id":123,"actual_status":"offline","intended_status":"stopped"}' ''')
        self.assertEqual(result.returncode, 77)

    def test_reported_boot_error_is_not_hidden_by_offline_grace(self):
        result = self.check('''check_instance_failure 123 '{"id":123,"actual_status":"offline","status_msg":"invalid image"}' ''')
        self.assertEqual(result.returncode, 77)

    def test_new_instance_gets_its_own_grace(self):
        result = self.check('''check_instance_failure 123 "$offline"
clock=300; check_instance_failure 456 "${offline/123/456}"
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_deleted_instance_stops_watcher(self):
        result = self.check('check_instance_failure 123 "{}"')
        self.assertEqual(result.returncode, 78)
        self.assertIn('no longer exists', result.stdout)

    def test_api_outage_is_not_treated_as_deletion(self):
        result = self.check('listing=unavailable; check_instance_failure 123 "{}"')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_instance_still_listed_is_not_treated_as_deleted(self):
        result = self.check('listing=\'[ {"id":123} ]\'; check_instance_failure 123 "{}"')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
