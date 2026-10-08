import os
from pathlib import Path
import pty
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VastProgressTests(unittest.TestCase):
    def test_cancelled_frame_exits_without_broken_pipe_traceback(self):
        import signal
        import sys
        script = (ROOT/'src/manager/progress.sh').read_text()
        frames = [('PY_VAST_PROGRESS', ['1', '10', '80', '', '0']),
                  ('PY_RENDER', ['80', '10', '{"tasks":{}}'])]
        for marker, args in frames:
            code = script.split("<<'"+marker+"'\n", 1)[1].split('\n'+marker, 1)[0]
            read_fd, write_fd = os.pipe()
            os.close(read_fd)
            try:
                process = subprocess.Popen([sys.executable, '-c', code, *args],
                                           stdout=write_fd, stderr=subprocess.PIPE)
            finally:
                os.close(write_fd)
            _, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, -signal.SIGPIPE)
            self.assertEqual(errors, b'')

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
        self.assertLessEqual(output.count('Verifying Checksum'), 1)
        self.assertIn('Preparing VM image', output)
        self.assertIn('Host:OK · Image:OK', output)
        self.assertIn('Elapsed 7m 41s', output)
        self.assertNotIn('\x1b', output)
        self.assertNotIn('%', output)
        self.assertNotIn('ETA', output)

    def test_provider_regressions_do_not_repeat_or_reset_boot_milestones(self):
        output=self.run_display("print_vast_progress provisioning '' 1; print_vast_progress loading '' 26; print_vast_progress provisioning '' 33; print_vast_progress loading '' 93")
        self.assertEqual(output.count('Allocating host'),1)
        self.assertEqual(output.count('Preparing VM image'),1)
        self.assertEqual(len(output.splitlines()),2)

    def test_terminal_updates_in_place_and_explains_stale_activity(self):
        output = self.run_display('''
print_vast_progress loading '5f914a314fb7: Verifying Checksum' 130
print_vast_progress loading '5f914a314fb7: Verifying Checksum' 190
progress_clear
''', terminal=True)
        self.assertIn('\r\x1b[K', output)
        self.assertIn('Elapsed 3m 10s', output)
        self.assertIn('Elapsed 3m 10s', output)

    def test_multiline_truncated_layer_and_terminal_control_characters(self):
        output = self.run_display("print_vast_progress loading $'layer: Verifying Checksum\\nlayer: \\a' 10")
        self.assertIn('Preparing VM image', output)
        self.assertNotIn('\x07', output)

    def test_failure_and_interrupt_clear_live_panel(self):
        provider = (ROOT/'src/manager/provider.sh').read_text()
        failure = provider.split('destroy_failed_prompt() {', 1)[1].split('collect_failure_report "$id"', 1)[0]
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
        self.assertEqual(output.count('\r\x1b[K'), 2)

    def test_restore_reuses_one_terminal_line_and_logs_only_changes(self):
        payload='{"version":1,"tasks":{"phase":{"action":"DRIVE"},"core":{"state":"done","action":"Runtime ready"},"game":{"state":"running","action":"Downloading","bytes":50,"total":100,"speed":10,"eta":5}}}'
        commands=f"print_bootstrap_progress 1 100.64.0.1 10 '{payload}'; print_bootstrap_progress 1 100.64.0.1 20 '{payload}'; progress_clear"
        terminal=self.run_display(commands, terminal=True)
        self.assertIn('\r\x1b[K',terminal)
        self.assertEqual(terminal.count('\n'),0)
        logs=self.run_display(commands)
        self.assertEqual(logs.count('VASTGAME'),1)
        self.assertIn('Game 50%',logs)

    def test_slow_probe_maintains_tenth_second_animation_without_extra_probes(self):
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
        self.assertGreaterEqual(output.count('Preparing VM image'), 8)
        markers = re.findall(r'Image:([|/\\-])', output)
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
