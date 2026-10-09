import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_installer', ROOT/'scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ArchitectureTests(unittest.TestCase):
    def test_install_preserves_user_data_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix='vastgame test ') as tmp:
            home = Path(tmp)
            config = home/'.config/vastgame'; config.mkdir(parents=True)
            (config/'games').mkdir()
            (config/'games/save.marker').write_bytes(b'keep my saves')
            (config/'template_hash').write_text('keep template')
            old = home/'.local/bin/vastgame'; old.parent.mkdir(parents=True)
            old.write_text('old command')
            client=config/'client'; client.mkdir(); (client/'moonlight_hud.so').write_bytes(b'local binary')
            installer.install(home)
            installer.install(home)
            self.assertEqual(old.resolve(), ROOT/'bin/vastgame')
            self.assertEqual((config/'runtime').resolve(), ROOT/'src/runtime')
            self.assertEqual((config/'games/save.marker').read_bytes(), b'keep my saves')
            self.assertEqual((config/'template_hash').read_text(), 'keep template')
            self.assertEqual((home/'.local/share/vastgame/native/moonlight_hud.so').read_bytes(), b'local binary')
            backups=list((home/'.local/state/vastgame/installation-backups').glob('previous-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0]/'vastgame').read_text(), 'old command')
            result=subprocess.run([str(old),'help'],env=self.environment(home),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('Vastgame',result.stdout)

    def environment(self, home):
        env=dict(os.environ,HOME=str(home))
        for name in ('XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME'):
            env.pop(name,None)
        return env

    def test_short_long_and_force_aliases_use_same_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); folder=home/'game'; folder.mkdir(); (folder/'Game.exe').touch()
            catalog=home/'.config/vastgame/games/fixture'; catalog.mkdir(parents=True)
            manifest=dict(schema=1,id='fixture',name='Game',source={'path':str(folder)},
                          game={'executable':'Game.exe'},runner={'version':'custom'},environment={})
            (catalog/'manifest.json').write_text(json.dumps(manifest))
            env=self.environment(home)
            # Account tools must exist for dependency checks, but may never run here.
            tools=home/'tools'; tools.mkdir()
            for name in ('vastai','tailscale'):
                path=tools/name; path.write_text('#!/bin/sh\necho unexpected-network-command >&2\nexit 99\n'); path.chmod(0o755)
            env['PATH']=str(tools)+':'+env['PATH']
            for args in (['inspect','fixture'],['game','inspect','fixture'],['force','game','inspect','fixture'],
                         ['validate','fixture'],['game','validate','fixture'],['select','fixture']):
                result=subprocess.run([str(ROOT/'bin/vastgame'),*args],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertNotIn('unexpected-network-command',result.stderr)
            self.assertEqual((home/'.local/state/vastgame/selected_game').read_text().strip(),'fixture')
            for args in (['list'],['game','list']):
                result=subprocess.run([str(ROOT/'bin/vastgame'),*args],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('fixture',result.stdout)

    def test_dispatches_state_aliases_once_without_vm_operations(self):
        commands=(ROOT/'src/manager/commands.sh').read_text()
        dispatcher=commands[commands.index('# Normalize long'):]
        stubs='STATEDIR=$(mktemp -d); trap \'rm -rf \"$STATEDIR\"\' EXIT; usage() { exit 90; }; state_backup() { echo "backup:$1"; }; state_restore() { echo "restore:$1"; }; '
        for args in (['backup','fixture'],['state','backup','fixture'],['restore','fixture'],['state','restore','fixture']):
            result=subprocess.run(['bash','-euc',stubs+dispatcher,'fixture',*args],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),':'.join([args[-2],args[-1]]))

    def test_bootstrap_secret_is_private_and_not_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); config=root/'private.json'; output=root/'packed.sh'
            config.write_text(json.dumps({'TS_AUTHKEY':"fixture with ' shell $ characters"}))
            result=subprocess.run(['python3',str(ROOT/'src/bootstrap/pack.py'),str(ROOT/'src/bootstrap/start.sh'),str(output)],
                                  env=dict(os.environ,VASTGAME_BOOTSTRAP_CONFIG=str(config)),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(output.stat().st_mode & 0o777,0o600)
            self.assertNotIn('fixture with', (ROOT/'src/bootstrap/start.sh').read_text())
            import base64,lzma
            payload=output.read_text().split("VASTGAME_BOOTSTRAP_B85' | xz -dc > \"$tmp\"\n",1)[1].split('\nVASTGAME_BOOTSTRAP_B85',1)[0]
            raw=lzma.decompress(base64.b85decode(payload))
            subprocess.run(['bash','-n'],input=raw,check=True)
            config.write_text('{"UNEXPECTED":"value"}')
            output.unlink()
            result=subprocess.run(['python3',str(ROOT/'src/bootstrap/pack.py'),str(ROOT/'src/bootstrap/start.sh'),str(output)],
                                  env=dict(os.environ,VASTGAME_BOOTSTRAP_CONFIG=str(config)),capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(output.exists())

    def test_confirmed_host_continues_across_source_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            (home/'.config/vastgame').mkdir(parents=True)
            (home/'.config/vastgame/template_hash').write_text('fixture-template')
            offer=dict(id=123,machine_id=456,gpu_name='RTX 5090',gpu_ram=32768,
                dph_total=0.584,vms_enabled=True,reliability=0.996,inet_up=614,
                inet_down=608,cpu_cores_effective=16,geolocation='Spain, ES',disk_bw=3606)
            fixture=home/'offers.json'; fixture.write_text(json.dumps([offer]))
            script=r'''set -Eeuo pipefail
APP_ROOT="$VASTGAME_TEST_ROOT"
source "$APP_ROOT/src/manager/common.sh"
source "$APP_ROOT/src/manager/client.sh"
calculate_disk_requirement() { :; }
all_vastgame_instances() { printf '[]\n'; }
native_screen_resolution() { echo 1920x1080; }
native_screen_refresh() { echo 60; }
SELECTED_GAME_FILE="$STATEDIR/selected_game"
connect_game() { echo UNEXPECTED_CONNECT; exit 99; }
setup_template() { echo UNEXPECTED_SETUP; exit 99; }
vastai() {
    [[ "$1 $2" == 'search offers' ]] || { echo UNEXPECTED_VAST_OPERATION; return 99; }
    [[ "$3" == *'verified=any'* && "$3" == *'gpu_arch=nvidia'* && "$3" == *'gpu_ram>=6'* ]] || return 98
    [[ "$3" != *'reliability>='* && "$3" != *'inet_up>='* && "$3" != *'inet_down>='* ]] || return 98
    cat "$VASTGAME_TEST_OFFERS"
}
source "$APP_ROOT/src/manager/hosts.sh"
printf 'CREATE_STAGE_REACHED:%s\n' "$offer_id"
'''
            for answer,continued in (('y',True),('Y',True),('',True),('n',False),('N',False)):
                with self.subTest(answer=answer):
                    result=subprocess.run(['bash','-c',script],input='1\n'+answer+'\n',
                        env=dict(self.environment(home),VASTGAME_TEST_ROOT=str(ROOT),VASTGAME_TEST_OFFERS=str(fixture)),
                        capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertEqual('CREATE_STAGE_REACHED:123' in result.stdout,continued)
                    self.assertNotIn('UNEXPECTED_',result.stdout)

    def test_complete_host_ranking_filter_runs_from_source(self):
        result=subprocess.run(['jq','--argjson','max','15','--argjson','cap','0.7',
            '--arg','selected_game','fixture','--arg','native_resolution','1920x1080',
            '--argjson','native_fps','60','--slurpfile','hist','/dev/null',
            '-L',str(ROOT/'src/providers/vast'),'-f',str(ROOT/'src/providers/vast/rank.jq')],input='[]',capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),[])

    def test_host_eligibility_includes_unverified_six_gb_and_datacenter_gpus(self):
        names=['RTX 3060', 'RTX 3070 Ti', 'RTX A6000', 'RTX PRO 6000',
               'RTX 6000 Ada', 'Quadro RTX 8000', 'Tesla T4', 'L4', 'A100 SXM4', 'H100', 'B200']
        base=dict(vms_enabled=True, gpu_ram=6144, dph_total=0.3,
                  reliability=0.5, inet_up=1, inet_down=2, cpu_cores_effective=4,
                  geolocation='Spain, ES', verified=False)
        offers=[dict(base,id=i+1,machine_id=i+1,gpu_name=name) for i,name in enumerate(names)]
        # The provider's authoritative vendor field also permits unfamiliar NVIDIA models.
        offers.append(dict(base,id=20,machine_id=20,gpu_name='Future accelerator',gpu_arch='nvidia'))
        offers.extend([
            dict(base,id=21,gpu_name='RTX 3060',gpu_ram=6143),
            dict(base,id=22,gpu_name='RTX 4090',dph_total=0.71),
            dict(base,id=23,gpu_name='RTX 4090',vms_enabled=False),
            dict(base,id=24,gpu_name='AMD MI300X',gpu_arch='amd'),
            dict(base,id=25,gpu_name='AMD MI300X'),
        ])
        result=subprocess.run(['jq','--argjson','max','30','--argjson','cap','0.7',
            '--arg','selected_game','fixture','--arg','native_resolution','1920x1080',
            '--argjson','native_fps','60','--slurpfile','hist','/dev/null',
            '-L',str(ROOT/'src/providers/vast'),'-f',str(ROOT/'src/providers/vast/rank.jq')],
            input=json.dumps(offers),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual({offer['id'] for offer in json.loads(result.stdout)},set(range(1,12)) | {20})

    def test_ranking_rewards_sufficient_affordable_gpu_and_measured_performance(self):
        import time
        base=dict(vms_enabled=True, gpu_ram=12288, reliability=0.99,
                  inet_up=500, inet_down=1000, cpu_cores_effective=8,
                  cpu_ghz=3.5, geolocation='Spain, ES', disk_bw=1000)
        offers=[dict(base,id=1,machine_id=1,gpu_name='RTX 3080 Ti',dph_total=0.175),
                dict(base,id=2,machine_id=2,gpu_name='RTX 5090',gpu_ram=32768,dph_total=0.7)]
        def rank(history):
            with tempfile.NamedTemporaryFile(mode='w') as f:
                json.dump(history,f); f.flush()
                return json.loads(subprocess.check_output(['jq',
                    '--argjson','max','15','--argjson','cap','0.7',
                    '--arg','selected_game','still','--arg','native_resolution','1920x1080',
                    '--argjson','native_fps','60','--slurpfile','hist',f.name,
                    '-L',str(ROOT/'src/providers/vast'),'-f',str(ROOT/'src/providers/vast/rank.jq')],
                    input=json.dumps(offers),text=True))
        clean=rank({})
        self.assertEqual(clean[0]['id'],1)
        self.assertEqual(clean[0]['_vg']['basis'],'Estimated')
        measured=rank({'machine:1':{'performance':dict(samples=30,updated=time.time(),
            game_id='still',resolution='1920x1080',target_fps=60,game_fps=20,
            delivery_score=100,game_delivery_score=33)}})
        self.assertEqual(measured[0]['id'],2)
        self.assertEqual(measured[1]['_vg']['basis'],'Game measured')

    def test_source_shell_and_python_syntax(self):
        for path in [ROOT/'bin/vastgame',*sorted((ROOT/'src').rglob('*.sh')),*sorted((ROOT/'packaging/windows').glob('*.sh'))]:
            subprocess.run(['bash','-n',str(path)],check=True,capture_output=True)
        for path in [*ROOT.joinpath('src').rglob('*.py'),*ROOT.joinpath('packaging/windows').glob('*.py')]:
            compile(path.read_text(),str(path),'exec')
