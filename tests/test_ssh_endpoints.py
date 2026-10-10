from support import cli_source
import json
import fcntl
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
session_event() { :; }
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
        self.assertNotIn('BACKUP_REQUIRED', result.stdout)
        self.assertNotIn('MUST_NOT_DESTROY', result.stdout)
        self.assertIn('no authenticated connection', result.stderr)

    def test_cli_and_desktop_unused_guest_skip_backup_with_one_endpoint_lookup(self):
        root = Path(__file__).resolve().parents[1]
        for desktop in (False, True):
            with self.subTest(desktop=desktop), tempfile.TemporaryDirectory() as temporary:
                code = r'''
source "$PROJECT/src/manager/persistence.sh"
session_event() { :; }
pick_instance() { echo 123; }
instance_json() { echo '{"id":123,"label":"vastgame-123"}'; }
verified_state_endpoint() { echo PROBE >> "$CALLS"; printf 'host\t22\n'; }
startup_shutdown_state() { [[ "$5" == $'host\t22' ]] || return 99; echo unstarted; }
safe_backup() { echo UNEXPECTED_BACKUP; return 99; }
destroy_verified() { [[ "$1" == 123 && "$2" == vastgame-123 ]] || return 99; echo "DESTROYED $1"; }
warn() { echo "$*" >&2; }
ok() { echo "$*"; }
die() { echo "$*" >&2; return 1; }
'''
                code += '\nstop_game 123 vastgame-123 '+('a'*32) if desktop else '\nstop_game'
                result = subprocess.run(['bash', '-Eeuo', 'pipefail', '-c', code],
                    env=dict(os.environ, PROJECT=str(root), STATEDIR=temporary, CALLS=str(Path(temporary)/'calls')), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertIn('Game never started; skipping backup', result.stdout)
                self.assertIn('DESTROYED 123', result.stdout)
                self.assertNotIn('UNEXPECTED_BACKUP', result.stdout)
                self.assertEqual((Path(temporary)/'calls').read_text().splitlines(), ['PROBE'])

    def test_changed_provider_label_after_backup_blocks_destruction(self):
        root = Path(__file__).resolve().parents[1]
        code = r'''
source "$PROJECT/src/manager/provider.sh"
source "$PROJECT/src/manager/persistence.sh"
session_event() { :; }
instance_json() { printf '%s\n' "$INFO"; }
verified_state_endpoint() { printf 'host\t22\n'; }
startup_shutdown_state() { echo started; }
safe_backup() { INFO='{"id":123,"label":"vastgame-999"}'; }
vastai() { echo MUST_NOT_DESTROY; return 99; }
warn() { echo "$*" >&2; }
ok() { echo "$*"; }
die() { echo "$*" >&2; exit 1; }
stop_game 123 vastgame-123
'''
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(['bash', '-Eeuo', 'pipefail', '-c', code],
                env=dict(os.environ, PROJECT=str(root), STATEDIR=temporary, INFO='{"id":123,"label":"vastgame-123"}'),
                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('MUST_NOT_DESTROY', result.stdout)
        self.assertIn('Destruction could not be confirmed', result.stderr)

    def test_explicit_force_skips_guest_and_backup_but_refuses_wrong_provider_label(self):
        root = Path(__file__).resolve().parents[1]
        code = r'''
source "$PROJECT/src/manager/persistence.sh"
session_event() { :; }
instance_json() { echo '{"id":123,"label":"vastgame-123"}'; }
verified_state_endpoint() { echo UNEXPECTED_SSH; return 99; }
safe_backup() { echo UNEXPECTED_BACKUP; return 99; }
destroy_verified() { [[ "$1" == 123 && "$2" == vastgame-123 ]] || return 99; echo DESTROYED; }
warn() { echo "$*" >&2; }
ok() { echo "$*"; }
'''
        with tempfile.TemporaryDirectory() as temporary:
            for label, success in (('vastgame-123', True), ('vastgame-999', False)):
                result = subprocess.run(['bash', '-Eeuo', 'pipefail', '-c', code+'\nstop_game 123 '+label+' "" --force'],
                    env=dict(os.environ, PROJECT=str(root), STATEDIR=temporary), capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)
                self.assertEqual('DESTROYED' in result.stdout, success)
                self.assertNotIn('UNEXPECTED_', result.stdout)

    def test_force_does_not_wait_behind_an_existing_backup_lock(self):
        root = Path(__file__).resolve().parents[1]
        source = (root/'src/manager/commands.sh').read_text()
        locking = source[source.index('# Lifecycle operations'):source.index('# Imports may overlap')]
        with tempfile.TemporaryDirectory() as temporary:
            with (Path(temporary)/'lifecycle.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                code = 'command=stop; set -- --force --instance-id 123 --label vastgame-123; die() { echo "$*" >&2; exit 99; };\n'+locking+'\necho FORCE_LOCK_ACQUIRED'
                result = subprocess.run(['bash', '-Eeuo', 'pipefail', '-c', code],
                    env=dict(os.environ, STATEDIR=temporary), capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertEqual(result.stdout.strip(), 'FORCE_LOCK_ACQUIRED')

    def test_force_destroy_verifies_label_and_treats_confirmed_absence_as_success(self):
        source = (Path(__file__).resolve().parents[1]/'src/manager/provider.sh').read_text()
        function = source[source.index('destroy_verified() {'):source.index('\n# ============================================================\n# ERROR HANDLING')]
        code = r'''
session_event() { :; }
instance_json() { [[ "$LOOKUP_FAILED" == 0 ]] && printf '%s\n' "$INFO"; }
vastai() {
    if [[ "$1" == destroy ]]; then echo DESTROY_REQUEST; else printf '%s\n' "$LISTING"; fi
}
warn() { echo "$*" >&2; }
''' + function + '\ndestroy_verified 123 vastgame-123'
        with tempfile.TemporaryDirectory() as temporary:
            for lookup, info, listing, success, destroy in (
                ('0', '{"id":123,"label":"vastgame-999"}', '[]', False, False),
                ('0', '{"id":123,"label":"vastgame-123"}', '[]', True, True),
                ('1', '', '[]', True, False),
                ('1', '', 'invalid API response', False, False),
            ):
                identity = Path(temporary)/'instance'; identity.write_text('123')
                result = subprocess.run(['bash', '-Eeuo', 'pipefail', '-c', code],
                    env=dict(os.environ, LOOKUP_FAILED=lookup, INFO=info, LISTING=listing, INSTANCE_FILE=str(identity)), capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)
                self.assertEqual('DESTROY_REQUEST' in result.stdout, destroy)
                self.assertEqual(identity.exists(), not success)

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

    def run_probe(self, primary='fail', public='match', info=None, tailnet=''):
        cli=cli_source()
        helper=cli[cli.index('verified_state_endpoint() {'):cli.index('\nremote_state()')]
        fixture=info or {'id':123,'ssh_host':'ssh9.vast.ai','ssh_port':27390,'public_ipaddr':'81.27.69.180',
                         'ports':{'22/tcp':[{'HostPort':'29242'},{'HostPort':'29242'}]}}
        code=r'''
warn() { printf '%s\n' "$*" >&2; }
get_vast_ip() { [[ -n "$TAILNET" ]] && printf '%s\n' "$TAILNET"; }
timeout() { shift; "$@"; }
ssh() {
    local destination="${@: -2:1}" mode
    printf '%s\n' "$destination" >> "$CALLS"
    if [[ "$destination" == root@100.* ]]; then [[ "$*" == *'ProxyCommand=tailscale nc %h %p'* ]] || return 99; fi
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
                         CALLS=str(calls),STATEDIR=tmp,TAILNET=tailnet,KNOWN_HOSTS=str(Path(tmp)/'known_hosts')),capture_output=True,text=True)
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

    def test_tailnet_uses_the_agent_proxy_before_public_endpoints(self):
        result, calls = self.run_probe(public='match', tailnet='100.76.110.5')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '100.76.110.5\t22')
        self.assertEqual(calls, ['root@100.76.110.5'])

    def test_tailnet_failure_falls_back_without_dropping_identity_checks(self):
        result, calls = self.run_probe(primary='match', public='fail', tailnet='100.76.110.5')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['root@100.76.110.5', 'root@ssh9.vast.ai'])

    def test_invalid_api_endpoints_are_not_executed(self):
        result,calls=self.run_probe(info={'ssh_host':'-oProxyCommand=bad','ssh_port':22,'public_ipaddr':'81.27.69.180',
                                         'ports':{'22/tcp':[{'HostPort':'70000'}]}})
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(calls,[])


if __name__=='__main__': unittest.main()
