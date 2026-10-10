from support import cli_source
import importlib.util
import json
import hashlib
import io
import tarfile
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
WINDOWS=ROOT/'packaging/windows'
spec=importlib.util.spec_from_file_location('windows_builder',WINDOWS/'export_accounts.py')
builder=importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
update_spec=importlib.util.spec_from_file_location('windows_update',WINDOWS/'build_update.py')
updater=importlib.util.module_from_spec(update_spec); update_spec.loader.exec_module(updater)


def desktop_fixture(root, commit='a'*40):
    executable = root/'vastgame-desktop.exe'
    content = bytearray(80)
    content[:2] = b'MZ'; content[60:64] = (64).to_bytes(4, 'little'); content[64:70] = b'PE\0\0\x64\x86'
    executable.write_bytes(content)
    (root/'desktop-build.json').write_text(json.dumps(dict(source_commit=commit, sha256=hashlib.sha256(content).hexdigest())))
    return executable


class WindowsUpdateTests(unittest.TestCase):
    def test_packaging_rejects_desktop_from_a_different_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = desktop_fixture(root, 'b'*40)
            with self.assertRaisesRegex(ValueError, 'source do not match'):
                updater.build(root/'release.zip', '1.1.0', commit='a'*40, desktop=executable)

    def test_checksum_is_read_as_text_and_still_verified(self):
        source = (WINDOWS/'Check-Updates.ps1').read_text()
        self.assertNotIn('.Content.Trim()', source)
        self.assertIn('-OutFile $checksumFile', source)
        self.assertIn('Get-Content -Raw -Encoding UTF8 -LiteralPath $checksumFile', source)
        self.assertIn('Get-FileHash -LiteralPath $zip -Algorithm SHA256', source)
        self.assertIn('Download checksum mismatch; no update applied.', source)

    def test_tailnet_ssh_proxy_preserves_binary_packets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'vastgame').mkdir()
            executable = root/'Tailscale.exe'
            executable.write_text('#!/bin/bash\ncat\n')
            executable.chmod(0o755)
            (root/'vastgame/windows.json').write_text(json.dumps({'tailscale': str(executable)}))
            bridge = root/'tailscale'
            bridge.write_bytes((WINDOWS/'windows-bridge.sh').read_bytes())
            packet = b'SSH-2.0-peer\r\n\x00\xff\x0d\x0a\x80\r\n'
            result = subprocess.run(['bash', str(bridge), 'nc', '100.76.110.5', '22'], input=packet,
                env=dict(os.environ, XDG_CONFIG_HOME=str(root)), capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, packet)

    def test_windows_bridge_preserves_configured_codec_and_pairing_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); moonlight=root/'Moonlight'; moonlight.mkdir()
            executable=moonlight/'Moonlight.exe'
            executable.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
            executable.chmod(0o755)
            config=root/'windows.json'; config.write_text(json.dumps({'application':str(root)}))
            bridge=root/'moonlight'; bridge.write_bytes((WINDOWS/'windows-bridge.sh').read_bytes())
            for arguments,expected in [
                (['stream','--video-codec','HEVC','--resolution','1920x1080','100.1.2.3','Vastgame - cyberpunk'],
                 ['stream','--video-codec','HEVC','--resolution','1920x1080','100.1.2.3','Vastgame - cyberpunk']),
                (['list','100.1.2.3'],['list','100.1.2.3']),
            ]:
                env=dict(os.environ,XDG_CONFIG_HOME=str(root))
                (root/'vastgame').mkdir(exist_ok=True)
                (root/'vastgame/windows.json').write_bytes(config.read_bytes())
                result=subprocess.run(['bash',str(bridge),*arguments],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout.splitlines(),expected)

    def test_public_package_needs_no_local_game_or_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'Vastgame.zip'
            updater.build(output,'1.1.0',commit='a'*40,desktop=desktop_fixture(output.parent))
            with zipfile.ZipFile(output) as archive:
                names=archive.namelist()
                self.assertIn('Vastgame/Install-Vastgame.ps1',names)
                self.assertIn('Vastgame/vastgame-desktop.exe',names)
                self.assertIn('Vastgame/Ensure-Desktop.ps1',names)
                self.assertIn('Vastgame/Check-Updates.ps1',names)
                self.assertIn('Vastgame/Edit-Stream-Settings.ps1',names)
                self.assertFalse(any('accounts.tar' in n or 'cyberpunk.json' in n for n in names))
                release=json.loads(archive.read('Vastgame/release.json'))
                self.assertEqual(release['version'],'1.1.0')
                import hashlib
                for name,digest in release['files'].items():
                    self.assertEqual(hashlib.sha256(archive.read('Vastgame/'+name)).hexdigest(),digest)
                with tarfile.open(fileobj=io.BytesIO(archive.read('Vastgame/backend.tar.gz'))) as backend:
                    self.assertIn('src/client/ludusavi.json.gz', backend.getnames())
                    self.assertIn('src/client/countries.json', backend.getnames())
                    self.assertIn('src/client/LUDUSAVI-LICENSE', backend.getnames())
                    self.assertIn('src/providers/vast/rank.jq', backend.getnames())

    def test_update_preserves_settings_and_rolls_back_backend_on_copy_failure(self):
        spec=importlib.util.spec_from_file_location('apply_update',WINDOWS/'apply_update.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); home=root/'home'; app=root/'windows'; bundle=root/'bundle'
            (app/'Moonlight').mkdir(parents=True);(app/'Moonlight/Moonlight.exe').touch()
            for name in ('.config/vastai/vast_api_key','.config/rclone/rclone.conf','.config/vastgame/template_hash'):
                path=home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('private fixture')
            backend=home/'.local/share/vastgame/app/bin/vastgame';backend.parent.mkdir(parents=True)
            backend.write_text('previous backend')
            (app/'stream.json').write_text('{"fps":90}')
            ts=root/'tailscale';ts.touch();ps=root/'powershell';ps.touch()
            output=root/'Vastgame.zip';updater.build(output,'1.1.0',commit='a'*40,desktop=desktop_fixture(output.parent))
            with zipfile.ZipFile(output) as archive: archive.extractall(bundle)
            original_replace=module.replace
            def failing(path,content,mode=0o600):
                if path == home/'.local/bin/moonlight': raise OSError('simulated file failure')
                return original_replace(path,content,mode)
            with patch.object(module,'replace',side_effect=failing):
                with self.assertRaises(OSError): module.apply(home,bundle/'Vastgame',app,ts,ps)
            self.assertEqual(backend.read_text(),'previous backend')
            self.assertEqual((app/'stream.json').read_text(),'{"fps":90}')
            self.assertEqual((home/'.config/vastai/vast_api_key').read_text(),'private fixture')

    def test_update_and_ingestion_share_catalog_lock(self):
        source=(WINDOWS/'apply_update.py').read_text()
        self.assertIn("('lifecycle.lock', 'catalog.lock')",source)
        self.assertNotIn('cyberpunk',source)

    def test_installed_shortcut_fetches_updates_and_existing_setup_routes_through_updater(self):
        shortcut=(WINDOWS/'Update-Vastgame.cmd').read_text()
        self.assertIn('if exist "%~dp0ready"',shortcut)
        self.assertIn('Check-Updates.ps1',shortcut)
        launcher=(WINDOWS/'Vastgame.cmd').read_text()
        self.assertIn('goto installed',launcher)
        self.assertIn('call "%LOCALAPPDATA%\\Vastgame\\Vastgame.cmd" %*',launcher)
        setup=(WINDOWS/'Install-Vastgame.ps1').read_text()
        self.assertLess(setup.index("'Update-Vastgame.ps1'"),setup.index('Copy-Item'))


class WindowsInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)

    def credentials(self):
        for name in ('.config/vastai/vast_api_key','.config/rclone/rclone.conf','.config/vastgame/template_hash','.ssh/id_ed25519','.ssh/id_ed25519.pub'):
            path=self.home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture secret')



    def test_only_required_personal_configuration_is_exported(self):
        self.credentials()
        for name in ('.local/state/vastgame/instance_id','.config/tailscale/device.state','.config/vastgame/games/still/game-v1.tar.zst'):
            path=self.home/name; path.parent.mkdir(parents=True,exist_ok=True);path.write_text('never export')
        manifest=self.home/'.config/vastgame/games/still/manifest.json'
        manifest.write_text(json.dumps(dict(id='still',source={'path':'/home/riad/games/still'},package={'size':123},game={'executable':'Game.exe'})))
        data=dict(builder.account_files(self.home))
        self.assertEqual(len(data),6)
        self.assertFalse(any('device.state' in name or 'instance_id' in name or name.endswith('.tar.zst') for name in data))
        game=json.loads(data['.config/vastgame/games/still/manifest.json'])
        self.assertNotIn('source',game); self.assertEqual(game['package']['size'],123)

    def test_missing_or_symlinked_key_prevents_export(self):
        self.credentials()
        path=self.home/'.ssh/id_ed25519';path.unlink()
        with self.assertRaises(ValueError): list(builder.account_files(self.home))
        path.symlink_to(self.home/'.config/vastai/vast_api_key')
        with self.assertRaises(ValueError): list(builder.account_files(self.home))

    def test_wsl_distribution_parsing_executes_with_null_characters(self):
        pwsh = shutil.which('pwsh') or str(Path.home()/'.local/state/vastgame/windows-build/powershell/pwsh')
        if not Path(pwsh).exists():
            self.skipTest('PowerShell is required for the executed parsing regression')
        setup = (WINDOWS/'Complete-Setup.ps1').read_text()
        expression = next(line.strip() for line in setup.splitlines() if line.strip().startswith('$distros ='))
        script = self.home/'parse.ps1'
        script.write_text('''$ErrorActionPreference = 'Stop'
foreach ($distroOutput in @("Ubuntu`0`r`0`n`0Vastgame`0`r`0`n`0", "Ubuntu`r`nVastgame`r`n", "")) {
''' + expression + '''
    ConvertTo-Json -Compress -InputObject @($distros)
}
''')
        result = subprocess.run([pwsh,'-NoProfile','-File',str(script)],
            env=dict(os.environ,DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1'),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([json.loads(line) for line in result.stdout.splitlines()],
                         [['Ubuntu','Vastgame'],['Ubuntu','Vastgame'],[]])


    def test_windows_prerequisite_repairs_and_restart_gate_execute(self):
        pwsh = shutil.which('pwsh') or str(Path.home()/'.local/state/vastgame/windows-build/powershell/pwsh')
        if not Path(pwsh).exists():
            self.skipTest('PowerShell required for executed Windows prerequisite tests')
        source = (WINDOWS/'Prepare-WSL.ps1').read_text()
        function = source[source.index('function Initialize-WSLPrerequisites'):source.index('\ntry {')]
        mocks = '''
$ErrorActionPreference = 'Stop'
$script:events = @()
function Get-CimInstance($ClassName) {
    if ($ClassName -eq 'Win32_ComputerSystem') { return [pscustomobject]@{HypervisorPresent=$hypervisor} }
    return [pscustomobject]@{VirtualizationFirmwareEnabled=$firmware}
}
function Get-WindowsOptionalFeature { return [pscustomobject]@{State=$featureState} }
function Enable-WindowsOptionalFeature { $script:events += 'enable-feature' }
function bcdedit.exe {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq '/enum') { return "hypervisorlaunchtype $boot" }
    $script:events += 'enable-boot'
}
function Get-Service {
    if ($missingService) { return $null }
    $s = [pscustomobject]@{Status='Stopped';StartType='Disabled'}
    $s | Add-Member -MemberType ScriptMethod -Name WaitForStatus -Value { param($status,$timeout) }
    return $s
}
function Set-Service { $script:events += 'enable-service' }
function Start-Service { $script:events += 'start-service' }
'''
        cases = [
            ('Enabled',True,True,'Auto',False,False,['enable-service','start-service'],None),
            ('Disabled',False,True,'Auto',False,True,['enable-feature','enable-feature'],None),
            ('EnablePending',False,True,'Auto',False,True,[],None),
            ('Enabled',False,True,'Off',False,True,['enable-boot'],None),
            ('Enabled',False,False,'Auto',False,None,[],'hardware virtualization'),
            ('Enabled',False,True,'Auto',False,None,[],'hypervisor is not running'),
            ('Enabled',True,True,'Auto',True,None,[],'Host Compute Service is missing'),
        ]
        for feature,hypervisor,firmware,boot,missing,restart,events,error in cases:
            with self.subTest(feature=feature,hypervisor=hypervisor,boot=boot,error=error):
                boolean = lambda value: '$true' if value else '$false'
                script = self.home/'prerequisite-test.ps1'
                script.write_text(f"$featureState='{feature}';$hypervisor={boolean(hypervisor)};$firmware={boolean(firmware)};$boot='{boot}';$missingService={boolean(missing)}\n" + mocks + function + '''
try {
    $restart = Initialize-WSLPrerequisites
    @{restart=$restart;events=@($script:events)} | ConvertTo-Json -Compress
} catch {
    @{error=$_.Exception.Message;events=@($script:events)} | ConvertTo-Json -Compress
}
''')
                result = subprocess.run([pwsh,'-NoProfile','-File',str(script)],
                    env=dict(os.environ,DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1'),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                data = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual(data['events'],events)
                if error: self.assertIn(error,data['error'])
                else: self.assertEqual(data['restart'],restart)
        setup = (WINDOWS/'Complete-Setup.ps1').read_text()
        gate = setup.index("if ($requirements.status -eq 'restart')")
        self.assertLess(gate,setup.index("'--import', 'Vastgame'"))
        self.assertIn('exit 0',setup[gate:setup.index("$ts = Join-Path")])

    def test_obsolete_repair_scripts_are_not_packaged(self):
        self.assertFalse(list(WINDOWS.glob('Repair-*')))
        self.assertTrue((WINDOWS/'Complete-Setup.ps1').is_file())

    def test_dns_repair_preserves_working_dns_and_restores_failed_changes(self):
        for mode in ('healthy','repair','failure','aptfailure'):
            with self.subTest(mode=mode):
                root=self.home/mode; root.mkdir(); bindir=root/'bin';bindir.mkdir()
                resolver=root/'resolv.conf';resolver.write_text('original resolver\n')
                resolver.chmod(0o600)
                conf=root/'wsl.conf';conf.write_text('[network]\ngenerateResolvConf=true\n[user]\ndefault=vastgame\n')
                getent=bindir/'getent'
                getent.write_text('#!/bin/bash\n[[ -z "$DNS_TEST_USER" ]] || echo "$DNS_TEST_USER" >> "$DNS_TEST_EVENTS"\nif [[ "$DNS_TEST_MODE" == aptfailure ]]; then [[ "$DNS_TEST_USER" != _apt ]]; exit $?; fi\n[[ "$DNS_TEST_MODE" == healthy ]] || { [[ "$DNS_TEST_MODE" == repair ]] && grep -q "nameserver 203.0.113.53" "$DNS_TEST_RESOLVER"; }\n')
                getent.chmod(0o755)
                for name,content in (
                    ('id','#!/bin/bash\n[[ "$1" == _apt ]]\n'),
                    ('runuser','#!/bin/bash\n[[ "$1 $2 $3" == "-u _apt --" ]] || exit 2\nshift 3\nexport DNS_TEST_USER=_apt\nexec "$@"\n')):
                    fake=bindir/name;fake.write_text(content);fake.chmod(0o755)
                events=root/'dns-events'
                script=root/'network.sh'
                script.write_text((WINDOWS/'prepare-network.sh').read_text().replace('/etc/resolv.conf',str(resolver)).replace('/etc/wsl.conf',str(conf)))
                result=subprocess.run(['bash',str(script),'203.0.113.1','203.0.113.53'],
                    env=dict(os.environ,PATH=str(bindir)+':'+os.environ['PATH'],DNS_TEST_MODE=mode,DNS_TEST_RESOLVER=str(resolver),DNS_TEST_EVENTS=str(events)),
                    preexec_fn=lambda: os.umask(0o077),capture_output=True,text=True)
                self.assertEqual(resolver.stat().st_mode & 0o777,0o644)
                if mode!='failure': self.assertIn('_apt',events.read_text())
                if mode=='repair':
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertIn('nameserver 203.0.113.53',resolver.read_text())
                    self.assertIn('generateResolvConf=false',conf.read_text())
                    self.assertIn('default=vastgame',conf.read_text())
                else:
                    self.assertEqual(result.returncode,1 if mode in ('failure','aptfailure') else 0,result.stderr)
                    self.assertEqual(resolver.read_text(),'original resolver\n')
                    self.assertIn('generateResolvConf=true',conf.read_text())

    def test_package_index_failure_stops_before_installation(self):
        bindir=self.home/'bin';bindir.mkdir()
        events=self.home/'apt-events'
        apt=bindir/'apt-get'
        apt.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$APT_TEST_EVENTS"\n[[ "$*" != *"APT::Update::Error-Mode=any"* ]]\n')
        apt.chmod(0o755)
        (self.home/'prepare-network.sh').write_text('exit 0\n')
        result=subprocess.run(['bash',str(WINDOWS/'install-backend.sh'),str(self.home),'unused','unused'],
            env=dict(os.environ,PATH=str(bindir)+':'+os.environ['PATH'],APT_TEST_EVENTS=str(events)),capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(len(events.read_text().splitlines()),1)
        self.assertNotIn('install',events.read_text())

    def test_native_powershell_bridge_works_without_windows_on_path(self):
        config=self.home/'.config/vastgame';config.mkdir(parents=True)
        bindir=self.home/'bin';bindir.mkdir()
        executable=self.home/'Windows PowerShell'/'powershell.exe';executable.parent.mkdir()
        executable.write_text('#!/bin/bash\ncase "$*" in *Native-Screen.ps1*) printf \'{"resolution":"2560x1440","refresh":144}\\r\\n\';; *Native-Ping.ps1*) printf "3 packets transmitted, 3 received, 0%% packet loss\\r\\n";; esac\n')
        executable.chmod(0o755)
        (config/'windows.json').write_text(json.dumps(dict(application=str(self.home),powershell=str(executable))))
        translate=bindir/'wslpath';translate.write_text('#!/bin/bash\nprintf "%s\\n" "$2"\n');translate.chmod(0o755)
        for name in ('vastgame-native','ping'):
            bridge=bindir/name;bridge.write_bytes((WINDOWS/'windows-bridge.sh').read_bytes());bridge.chmod(0o755)
        env=dict(os.environ,HOME=str(self.home),XDG_CONFIG_HOME=str(self.home/'.config'),PATH=str(bindir)+':/usr/bin:/bin')
        self.assertIsNone(shutil.which('powershell.exe',path=env['PATH']))
        for arguments,expected in ((['vastgame-native','resolution'],'2560x1440'),(['vastgame-native','refresh'],'144'),(['ping','-c','3','127.0.0.1'],'3 packets transmitted, 3 received, 0% packet loss')):
            result=subprocess.run(arguments,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),expected)

    def test_windows_and_linux_moonlight_app_lists_match_exact_game(self):
        cli=cli_source()
        start=cli.index('    set +e',cli.index('echo "Checking Moonlight pairing..."'))
        end=cli.index('    if (( rc != 0 )); then',start)
        capture=cli[start:end]
        moonlight=self.home/'moonlight'
        moonlight.write_text('#!/bin/bash\ncat "$APP_LIST_FIXTURE"\n');moonlight.chmod(0o755)
        for newline in ('\n','\r\n'):
            with self.subTest(newline=newline):
                listing=self.home/'apps.txt'
                listing.write_bytes(('Wolf UI'+newline+'Vastgame - still'+newline+'Vastgame - still-more'+newline).encode())
                code='set -e; ip=127.0.0.1; ml=("$MOONLIGHT_LIST_FIXTURE"); '+capture+'''\n
grep -Fqx -- 'Vastgame - still' <<< "$list_out"
if grep -Fqx -- 'Vastgame - stil' <<< "$list_out"; then exit 99; fi
printf '%s\\n' "$list_out"
'''
                result=subprocess.run(['bash','-c',code],env=dict(os.environ,APP_LIST_FIXTURE=str(listing),MOONLIGHT_LIST_FIXTURE=str(moonlight)),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertNotIn('\r',result.stdout)
                self.assertEqual(result.stdout.splitlines(),['Wolf UI','Vastgame - still','Vastgame - still-more'])

    def test_windows_screen_detection_bypasses_linux_desktop(self):
        cli=cli_source()
        helper=cli[cli.index('native_screen_resolution() {'):cli.index('\nstream_settings_file()')]
        code='VASTGAME_WINDOWS=1; vastgame-native() { case "$1" in resolution) echo 3840x2160;; refresh) echo 120;; esac; }; '+helper+'\nnative_screen_resolution; native_screen_refresh'
        result=subprocess.run(['bash','-e','-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.splitlines(),['3840x2160','120'])

    def test_native_windows_folder_translation_preserves_literal_arguments(self):
        backend=self.home/'.local/share/vastgame/app/bin/vastgame'; backend.parent.mkdir(parents=True)
        backend.write_text('#!/usr/bin/env python3\nimport sys,json;print(json.dumps(sys.argv[1:]))\n'); backend.chmod(0o755)
        bindir=self.home/'bin'; bindir.mkdir()
        account=bindir/'getent'; account.write_text('#!/bin/sh\nprintf \'vastgame:x:1000:1000::%s:/bin/bash\\n\' \"$FIXTURE_HOME\"\n'); account.chmod(0o755)
        translate=bindir/'wslpath';translate.write_text('#!/usr/bin/env python3\nimport sys;print("/mnt/"+sys.argv[2][0].lower()+sys.argv[2][2:].replace(chr(92),"/"))\n');translate.chmod(0o755)
        result=subprocess.run(['bash',str(WINDOWS/'run-vastgame.sh'),'add',r'D:\Games\My Game','$(literal)'],
            env=dict(os.environ,HOME=str(self.home),FIXTURE_HOME=str(self.home),PATH=str(bindir)+':'+os.environ['PATH']),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),['add','/mnt/d/Games/My Game','$(literal)'])

    def test_setup_never_rents_or_destroys_a_vm_or_unregisters_wsl(self):
        setup=(WINDOWS/'Complete-Setup.ps1').read_text()+(WINDOWS/'install-backend.sh').read_text()
        self.assertNotIn('--unregister',setup)
        self.assertNotIn('destroy instance',setup)
        self.assertNotIn('create instance',setup)
        self.assertIn('vastai show user',setup)
        self.assertIn('rclone lsd gdrive:VastGaming',setup)
        self.assertIn('CurrentTailnet.Name',setup)



if __name__=='__main__': unittest.main()
