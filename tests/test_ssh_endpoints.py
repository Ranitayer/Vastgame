from support import cli_source
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class EndpointTests(unittest.TestCase):
    def test_loading_provider_and_no_local_request_cannot_skip_backup(self):
        root = Path(__file__).resolve().parents[1]
        code = '''
source "$PROJECT/src/manager/persistence.sh"
instance_json() { echo '{"id":123,"label":"vastgame-123","actual_status":"loading"}'; }
verified_state_endpoint() { return 1; }
valid_game_id() { [[ "$1" == fixture ]]; }
safe_backup() { echo BACKUP_REQUIRED; return 1; }
destroy_verified() { echo MUST_NOT_DESTROY; return 99; }
warn() { echo "$*" >&2; }
ok() { echo "$*"; }
die() { echo "$*" >&2; return 1; }
stop_game 123 vastgame-123 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
'''
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)/'desktop'/('a'*32); folder.mkdir(parents=True)
            (folder/'job.json').write_text(json.dumps(dict(job='a'*32, instance_id='123', label='vastgame-123', game='fixture', game_requested=False)))
            result = subprocess.run(['bash', '-Eeuo', 'pipefail', '-c', code],
                env=dict(os.environ, PROJECT=str(root), STATEDIR=temporary, RUNTIME_DIR=str(root/'src/runtime')),
                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('BACKUP_REQUIRED', result.stdout)
        self.assertNotIn('MUST_NOT_DESTROY', result.stdout)
        self.assertIn('No destroy request sent', result.stderr)

    def test_backup_uses_guest_manifest_and_isolated_helper_without_local_manifest(self):
        root=Path(__file__).resolve().parents[1]
        code='''
source "$PROJECT/src/manager/persistence.sh"
instance_json() { echo '{"id":123,"label":"vastgame-123"}'; }
verified_state_endpoint() { printf 'host\\t22\\n'; }
valid_game_id() { [[ "$1" == fixture ]]; }
game_manifest() { echo 'LOCAL_MANIFEST_MUST_NOT_BE_USED' >&2; return 99; }
warn() { echo "$*" >&2; }
ssh() {
    command="${@: -1}"
    printf '%s\\n' "$command" >> "$CALLS"
    case "$command" in
        'cat /var/lib/vast-gaming/status/instance-label') echo vastgame-123 ;;
        'cat /var/lib/vast-gaming/status/session.json') echo '{"game_id":"fixture"}' ;;
        'cat /srv/gaming/profiles/fixture/manifest.json') echo '{"schema":1,"id":"fixture","state":{"saves":["custom/save"]}}' ;;
        'bash -c '*) cat > "$UPLOADED_HELPER" ;;
        'python3 /opt/vastgame-state/'*) [[ "$command" == *'--manifest-sha '* ]] ;;
        'cat /srv/gaming/profiles/fixture/backup-receipt.json') echo '{"schema":1,"instance_id":"123","game_id":"fixture","snapshot":"verified"}' ;;
        *) echo 'Unexpected SSH command' >&2; return 98 ;;
    esac
}
remote_state backup 123 fixture
'''
        with tempfile.TemporaryDirectory() as tmp:
            result=subprocess.run(['bash','-Eeuo','pipefail','-c',code],
                env=dict(os.environ,PROJECT=str(root),STATEDIR=tmp,RUNTIME_DIR=str(root/'src/runtime'),
                         CALLS=str(Path(tmp)/'calls'),UPLOADED_HELPER=str(Path(tmp)/'helper')),
                capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            commands=(Path(tmp)/'calls').read_text()
            self.assertNotIn('cat > /srv/gaming/profiles', commands)
            self.assertNotIn('tar -C /opt/vastgame', commands)
            self.assertNotIn('LOCAL_MANIFEST', result.stderr)
            self.assertEqual((Path(tmp)/'helper').read_bytes(), (root/'src/runtime/game_state.py').read_bytes())

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
