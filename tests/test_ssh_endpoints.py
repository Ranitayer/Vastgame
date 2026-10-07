from support import cli_source
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class EndpointTests(unittest.TestCase):
    def run_probe(self, primary='fail', public='match', info=None):
        cli=cli_source()
        helper=cli[cli.index('verified_state_endpoint() {'):cli.index('\nremote_state()')]
        fixture=info or {'ssh_host':'ssh9.vast.ai','ssh_port':27390,'public_ipaddr':'81.27.69.180',
                         'ports':{'22/tcp':[{'HostPort':'29242'},{'HostPort':'29242'}]}}
        code=r'''
warn() { printf '%s\n' "$*" >&2; }
timeout() { shift; "$@"; }
ssh() {
    local destination="${@: -2:1}" mode
    printf '%s\n' "$destination" >> "$CALLS"
    if [[ "$destination" == root@ssh9.vast.ai ]]; then mode="$PRIMARY"; else mode="$PUBLIC"; fi
    case "$mode" in
        match) printf '%s\n' 'vastgame-123' ;;
        wrong) printf '%s\n' 'vastgame-999' ;;
        fail) return 255 ;;
    esac
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            calls=Path(tmp)/'calls'
            result=subprocess.run(['bash','-e','-c',code+helper+'\nverified_state_endpoint "$INFO" vastgame-123'],
                env=dict(os.environ,INFO=json.dumps(fixture),PRIMARY=primary,PUBLIC=public,
                         CALLS=str(calls),KNOWN_HOSTS=str(Path(tmp)/'known_hosts')),capture_output=True,text=True)
            attempted=calls.read_text().splitlines() if calls.exists() else []
        return result,attempted

    def test_refused_relay_uses_verified_public_port(self):
        result,calls=self.run_probe()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'81.27.69.180\t29242')
        self.assertEqual(calls,['root@ssh9.vast.ai','root@81.27.69.180'])

    def test_working_relay_does_not_probe_other_servers(self):
        result,calls=self.run_probe(primary='match')
        self.assertEqual(result.returncode,0)
        self.assertEqual(calls,['root@ssh9.vast.ai'])

    def test_wrong_identity_refuses_state_changes(self):
        result,calls=self.run_probe(primary='wrong')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertEqual(calls,['root@ssh9.vast.ai'])

    def test_all_unreachable_deduplicates_and_retains_vm(self):
        result,calls=self.run_probe(public='fail')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(len(calls),2)
        self.assertIn('VM retained',result.stderr)

    def test_invalid_api_endpoints_are_not_executed(self):
        result,calls=self.run_probe(info={'ssh_host':'-oProxyCommand=bad','ssh_port':22,'public_ipaddr':'81.27.69.180',
                                         'ports':{'22/tcp':[{'HostPort':'70000'}]}})
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(calls,[])


if __name__=='__main__': unittest.main()
