import os
from pathlib import Path
import pty
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VastProgressTests(unittest.TestCase):
    def run_display(self, commands, terminal=False):
        script = f'set -Eeuo pipefail; source "{ROOT}/src/manager/progress.sh"; {commands}'
        if not terminal:
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(['bash', '-c', script], stdout=slave,
                                       stderr=slave, env=dict(os.environ, TERM='xterm'))
            os.close(slave)
            slave = None
            chunks = []
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
            self.assertEqual(process.wait(timeout=5), 0)
            return b''.join(chunks).decode()
        finally:
            os.close(master)
            if slave is not None:
                os.close(slave)

    def test_redirected_output_only_logs_changes(self):
        output = self.run_display('''
print_vast_progress provisioning '' 0
print_vast_progress loading '5f914a314fb7: Verifying Checksum' 130
print_vast_progress loading '5f914a314fb7: Verifying Checksum' 160
print_vast_progress created 'success, running image' 328
print_vast_progress running 'success, running image' 461
''')
        self.assertEqual(output.count('Verifying Checksum'), 1)
        self.assertIn('Preparing VM image', output)
        self.assertIn('[OK] Host  →  [OK] Image', output)
        self.assertIn('Elapsed 7m 41s', output)
        self.assertNotIn('\x1b', output)
        self.assertNotIn('%', output)
        self.assertNotIn('ETA', output)

    def test_terminal_updates_in_place_and_explains_stale_activity(self):
        output = self.run_display('''
print_vast_progress loading '5f914a314fb7: Verifying Checksum' 130
print_vast_progress loading '5f914a314fb7: Verifying Checksum' 190
progress_clear
''', terminal=True)
        self.assertIn('\x1b[3A\x1b[J', output)
        self.assertIn('No new host update for 1m 00s', output)
        self.assertIn('Elapsed 3m 10s', output)

    def test_multiline_truncated_layer_and_terminal_control_characters(self):
        output = self.run_display("print_vast_progress loading $'layer: Verifying Checksum\\nlayer: \\a' 10")
        self.assertIn('Verifying Checksum', output)
        self.assertNotIn('\x07', output)

    def test_failure_and_interrupt_clear_live_panel(self):
        provider = (ROOT/'src/manager/provider.sh').read_text()
        failure = provider.split('destroy_failed_prompt() {', 1)[1].split('show_vast_diagnostics "$id"', 1)[0]
        self.assertIn('progress_clear', failure)
        launch = (ROOT/'src/manager/launch.sh').read_text()
        self.assertIn("trap '\n    progress_stop_animation\n    progress_clear", launch)
        self.assertIn('print_vast_progress "$actual" "$msg" "$e"', launch)
        self.assertNotIn('last_print', launch)

    def test_tailscale_wait_does_not_repeat_in_redirected_logs(self):
        output = self.run_display('''elapsed() { printf '%sm %02ds' "$(( $1 / 60 ))" "$(( $1 % 60 ))"; }
print_tailscale_progress 0
print_tailscale_progress 6
print_tailscale_progress 110
''')
        self.assertEqual(output.count('Waiting for vast-gaming'), 1)
        self.assertNotIn('\x1b', output)

    def test_tailscale_wait_is_one_live_line(self):
        output = self.run_display('''elapsed() { printf '%sm %02ds' "$(( $1 / 60 ))" "$(( $1 % 60 ))"; }
print_tailscale_progress 0
print_tailscale_progress 110
progress_clear
''', terminal=True)
        self.assertIn('Elapsed 1m 50s', output)
        self.assertEqual(output.count('\x1b[1A\x1b[J'), 2)

    def test_slow_probe_maintains_half_second_animation_without_extra_probes(self):
        import re
        output = self.run_display('''start=$(date +%s)
actual=loading
msg='Verifying Checksum'
probe() { sleep 1.7; echo result; }
progress_run vast_wait_frame probe
printf 'PROBE:%s\\n' "$VG_POLL_OUTPUT"
[[ -z "$VG_PROGRESS_ANIMATION_PID" ]]
progress_clear
''', terminal=True)
        self.assertGreaterEqual(output.count('Preparing VM image'), 4)
        markers = re.findall(r'\[([|/\\-])\] Image', output)
        self.assertGreaterEqual(len(set(markers)), 3)
        self.assertEqual(output.count('PROBE:result'), 1)

    def test_failed_probe_preserves_status_and_cleans_animation(self):
        output = self.run_display('''start=$(date +%s)
actual=loading
msg=''
probe() { sleep 0.6; echo failed; return 7; }
if progress_run vast_wait_frame probe; then exit 99; else result=$?; fi
[[ "$result" == 7 && -z "$VG_PROGRESS_ANIMATION_PID" ]]
printf 'RC:%s\\n' "$result"
progress_clear
''', terminal=True)
        self.assertIn('RC:7', output)
