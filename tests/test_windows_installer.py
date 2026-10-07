from support import cli_source
import importlib.util
import json
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
spec=importlib.util.spec_from_file_location('windows_builder',WINDOWS/'build_installer.py')
builder=importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class WindowsInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)

    def credentials(self):
        for name in ('.config/vastai/vast_api_key','.config/rclone/rclone.conf','.config/vastgame/template_hash','.ssh/id_ed25519','.ssh/id_ed25519.pub'):
            path=self.home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture secret')

    def test_staged_backend_includes_offline_save_catalog_and_license(self):
        self.credentials()
        assets = self.home/'assets'; assets.mkdir()
        (assets/'tailscale.msi').write_bytes(b'fixture')
        with zipfile.ZipFile(assets/'moonlight.zip', 'w') as archive:
            archive.writestr('Moonlight.exe', b'fixture')
        with tarfile.open(assets/'ubuntu-root.tar.xz', 'w:xz') as archive:
            builder.add_bytes(archive, 'etc/fixture', b'fixture')
        for name in ('.local/bin/vastgame', '.config/vastgame/vast-gaming-start-v2.sh',
                     '.config/Moonlight Game Streaming Project/Moonlight.conf'):
            path=self.home/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'fixture')
        (self.home/'.config/vastgame/runtime').mkdir()
        client=self.home/'.config/vastgame/client'; client.mkdir()
        (client/'ludusavi.json.gz').write_bytes(b'offline catalog')
        (client/'LUDUSAVI-LICENSE').write_bytes(b'upstream license')
        with patch.object(builder,'checked'):
            builder.stage(self.home,assets,self.home/'payload','fixture-tailnet')
        with tarfile.open(self.home/'payload/backend.tar') as archive:
            self.assertEqual(archive.extractfile('.local/share/vastgame/app/src/client/ludusavi.json.gz').read(),(ROOT/'src/client/ludusavi.json.gz').read_bytes())
            self.assertEqual(archive.extractfile('.local/share/vastgame/app/src/client/LUDUSAVI-LICENSE').read(),(ROOT/'src/client/LUDUSAVI-LICENSE').read_bytes())
            staged=self.home/'staged-home'; staged.mkdir()
            archive.extractall(staged,filter='data')
        app=staged/'.local/share/vastgame/app'
        self.assertEqual((app/'bin/vastgame').read_bytes(),(ROOT/'bin/vastgame').read_bytes())
        self.assertTrue((app/'src/providers/vast/rank.jq').is_file())
        for path in (ROOT/'src/manager').glob('*.sh'):
            self.assertEqual((app/'src/manager'/path.name).read_bytes(),path.read_bytes())
        env=dict(os.environ,HOME=str(staged),VASTGAME_WINDOWS='1')
        for name in ('XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME'):
            env.pop(name,None)
        result=subprocess.run([str(app/'bin/vastgame'),'help'],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('vastgame start <game-id>',result.stdout)
        self.assertNotIn(str(ROOT), result.stdout)
        # The deployed dispatcher must reach the packaged Python helpers as well.
        source=staged/'Game'; source.mkdir(); (source/'Game.exe').touch()
        manifest=staged/'.config/vastgame/games/fixture/manifest.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({'schema':1,'id':'fixture','name':'Game',
            'source':{'path':str(source)},'game':{'executable':'Game.exe'}}))
        for args in (['inspect','fixture'],['game','validate','fixture']):
            result=subprocess.run([str(app/'bin/vastgame'),*args],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


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

    def test_cloud_image_dns_is_replaced_with_wsl_generation(self):
        source=self.home/'ubuntu.tar.xz'; target=self.home/'wsl.tar.gz'
        with tarfile.open(source,'w:xz') as archive:
            link=tarfile.TarInfo('etc/resolv.conf'); link.type=tarfile.SYMTYPE
            link.linkname='../run/systemd/resolve/stub-resolv.conf';archive.addfile(link)
            builder.add_bytes(archive,'etc/example',b'preserve official files')
        builder.prepare_wsl_root(source,target)
        with tarfile.open(target,'r:gz') as archive:
            self.assertNotIn('etc/resolv.conf',archive.getnames())
            conf=archive.extractfile('etc/wsl.conf').read()
            self.assertIn(b'generateResolvConf=true',conf)
            self.assertIn(b'systemd=false',conf)
            self.assertEqual(archive.extractfile('etc/example').read(),b'preserve official files')

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
        helper=cli[cli.index('native_screen_resolution() {'):cli.index('\nmoonlight_game_options()')]
        code='VASTGAME_WINDOWS=1; vastgame-native() { case "$1" in resolution) echo 3840x2160;; refresh) echo 120;; esac; }; '+helper+'\nnative_screen_resolution; native_screen_refresh'
        result=subprocess.run(['bash','-e','-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.splitlines(),['3840x2160','120'])

    def test_native_windows_folder_translation_preserves_literal_arguments(self):
        backend=self.home/'.local/share/vastgame/app/bin/vastgame'; backend.parent.mkdir(parents=True)
        backend.write_text('#!/usr/bin/env python3\nimport sys,json;print(json.dumps(sys.argv[1:]))\n'); backend.chmod(0o755)
        bindir=self.home/'bin'; bindir.mkdir()
        translate=bindir/'wslpath';translate.write_text('#!/usr/bin/env python3\nimport sys;print("/mnt/"+sys.argv[2][0].lower()+sys.argv[2][2:].replace(chr(92),"/"))\n');translate.chmod(0o755)
        result=subprocess.run(['bash',str(WINDOWS/'run-vastgame.sh'),'add',r'D:\Games\My Game','$(literal)'],
            env=dict(os.environ,HOME=str(self.home),PATH=str(bindir)+':'+os.environ['PATH']),capture_output=True,text=True)
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

    def test_installer_encryption_and_safe_default_setup(self):
        script=(WINDOWS/'installer.iss').read_text()
        self.assertIn('Encryption=yes',script)
        self.assertIn('Password={#InstallerPassword}',script)
        self.assertIn('EncryptionKeyDerivation=pbkdf2/600000',script)
        self.assertIn('PrivilegesRequired=lowest',script)
        self.assertNotIn('postinstall unchecked',script)
        self.assertIn("'--import', 'Vastgame'",(WINDOWS/'Complete-Setup.ps1').read_text())


if __name__=='__main__': unittest.main()
