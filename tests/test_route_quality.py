from support import cli_source
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class RouteQualityTests(unittest.TestCase):
    def qualify(self, summary, loss='0'):
        cli=cli_source()
        history=cli[cli.index('record_route_history() ('):cli.index('\n# ============================================================\n# TEMPLATE')]
        qualify=cli[cli.index('qualify_local_route() {'):cli.index('\n# ============================================================\n# BOOTSTRAP PROGRESS')]
        stubs='''
bold() { :; }; ok() { :; }; warn() { echo "$*" >&2; }
timeout() { shift; "$@"; }
tailscale() { echo 'pong from host via 1.2.3.4:123 in 95ms'; }
ping() { printf '%s\\n' "$PING_OUTPUT"; }
instance_json() { echo '{"machine_id":148067,"host_id":42}'; }
VASTGAME_FORCE_ROUTE=0
LOCAL_MAX_RTT_MS=120
LOCAL_MAX_LOSS_PCT=1
LOCAL_MAX_JITTER_MS=15
'''
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'history.json'
            result=subprocess.run(['bash','-e','-c',stubs+history+'\n'+qualify+'\nqualify_local_route 123 100.87.47.86'],
                env=dict(os.environ,STATEDIR=tmp,HISTORY_FILE=str(path),
                         PING_OUTPUT=f'20 packets transmitted, 20 received, {loss}% packet loss, time 3821ms\n{summary}'),
                capture_output=True,text=True)
            data=json.loads(path.read_text())['machine:148067']
        return result,data

    def test_pipe_suffix_is_ignored_and_real_jitter_still_rejects_route(self):
        result,data=self.qualify('rtt min/avg/max/mdev = 48.000/95.277/201.000/46.364 ms, pipe 2')
        self.assertEqual(result.returncode,1)
        self.assertEqual(data['jitter_ms'],46.364)
        self.assertEqual(data['last_result'],'fail')
        self.assertIn('46.364 ms',result.stdout)
        self.assertNotIn('invalid JSON',result.stderr)
        self.assertNotIn('pipe2',result.stdout)

    def test_extra_ping_summary_fields_do_not_break_good_route(self):
        result,data=self.qualify('rtt min/avg/max/mdev = 75.000/95.277/110.000/10.364 ms, pipe 2, ipg/ewma 200.000/95.000 ms')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(data['jitter_ms'],10.364)
        self.assertEqual(data['last_result'],'pass')

    def test_standard_round_trip_summary_is_supported(self):
        result,data=self.qualify('round-trip min/avg/max/stddev = 75.000/95.277/110.000/10.364 ms')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(data['avg_rtt_ms'],95.277)

    def test_malformed_values_fail_closed_without_invalid_json(self):
        result,data=self.qualify('rtt min/avg/max/mdev = 75.000/95.277/110.000/not-a-number ms')
        self.assertEqual(result.returncode,1)
        self.assertEqual(data['jitter_ms'],999)
        self.assertIn('Could not measure route quality',result.stderr)
        self.assertNotIn('invalid JSON',result.stderr)


if __name__=='__main__': unittest.main()
