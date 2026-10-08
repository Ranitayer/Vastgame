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
pause_boot_wait() {{ echo "$2"; exit 79; }}
record_instance_event() {{ :; }}
CLIENT_DIR=/unused
STATEDIR=/unused
python3() {{ cat >/dev/null; }}
die() {{ echo "$*"; exit 78; }}
INSTANCE_FILE=/dev/null
listing='[]'
vastai() {{ echo "$listing"; }}
timeout() {{ shift; "$@"; }}
clock=100
date() {{ echo "$clock"; }}
progress_run() {{ shift; VG_POLL_OUTPUT="$log"; return "$log_rc"; }}
log=''
log_rc=0
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

    def test_persistent_offline_pauses_without_claiming_host_failure(self):
        result = self.check('''check_instance_failure 123 "$offline"
clock=190; check_instance_failure 123 "$offline"
''')
        self.assertEqual(result.returncode, 79)
        self.assertIn('availability is unconfirmed', result.stdout)

    def test_intended_stop_is_not_proof_of_failed_boot(self):
        result = self.check('''check_instance_failure 123 '{"id":123,"actual_status":"offline","intended_status":"stopped"}' ''')
        self.assertEqual(result.returncode, 0)

    def test_planned_stop_does_not_abort_a_created_or_running_guest(self):
        result = self.check('''check_instance_failure 123 '{"id":123,"actual_status":"created","intended_status":"running","next_state":"stopped"}'
check_instance_failure 123 '{"id":123,"actual_status":"running","intended_status":"running","next_state":"stopped"}'
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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

    def test_bootstrap_failure_stops_before_tailscale(self):
        result = self.check('''log='[VASTGAME] ERROR: Bootstrap did not enter the systemd VM guest.'
check_startup_logs 123 "$loading" unused
''')
        self.assertEqual(result.returncode, 77)
        self.assertIn('did not enter', result.stdout)

    def test_missing_domain_initial_lookup_is_not_failure(self):
        result = self.check('''log="libvirt: QEMU Driver error : Domain not found: no domain with matching name 'C.123'"
created='{"id":123,"actual_status":"created"}'
check_startup_logs 123 "$created" unused
clock=399; check_startup_logs 123 "$created" unused
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_domain_after_five_minutes_remains_pending(self):
        result = self.check('''log="libvirt: QEMU Driver error : Domain not found: no domain with matching name 'C.123'"
created='{"id":123,"actual_status":"created"}'
check_startup_logs 123 "$created" unused
clock=400; check_startup_logs 123 "$created" unused
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_log_api_failure_is_not_a_host_failure(self):
        result = self.check('''log_rc=1
check_startup_logs 123 "$loading" unused
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_guest_boot_resets_missing_domain_timer(self):
        result = self.check('''log="libvirt: QEMU Driver error : Domain not found: no domain with matching name 'C.123'"
created='{"id":123,"actual_status":"created"}'
check_startup_logs 123 "$created" unused
clock=130; log='[VASTGAME] PHASE=BOOT'; check_startup_logs 123 "$created" unused
clock=400; log="libvirt: QEMU Driver error : Domain not found: no domain with matching name 'C.123'"
check_startup_logs 123 "$created" unused
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_old_gpu_log_does_not_override_running_status(self):
        result = self.check('''log='Error: GPU error, unable to start instance.'
instance_json() { echo '{"id":123,"actual_status":"running"}'; }
check_startup_logs 123 "$loading" unused
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_gpu_status_error_is_not_hidden_by_intended_stop(self):
        result = self.check('''check_instance_failure 123 '{"id":123,"actual_status":"created","intended_status":"stopped","status_msg":"Error: GPU error, unable to start instance."}' ''')
        self.assertEqual(result.returncode, 77)
        self.assertIn('GPU error', result.stdout)

    def test_running_status_overrides_old_error_message(self):
        result = self.check('''check_instance_failure 123 '{"id":123,"actual_status":"running","status_msg":"failed to start"}' ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
