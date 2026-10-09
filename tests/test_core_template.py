import base64
import importlib.util
import json
import lzma
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('core_template', ROOT/'scripts/create-core-template.py')
creator = importlib.util.module_from_spec(spec); spec.loader.exec_module(creator)


class CoreTemplateTests(unittest.TestCase):
    def test_template_create_verify_activate_and_repeat_without_duplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=Path(tmp)/'vastgame'; cfg.mkdir(); selected=cfg/'template_hash'; selected.write_text('previous\n')
            original=dict(creator_id=123,env='-e TS_AUTHKEY=fixture -e RCLONE_CONFIG_B64=cGF5bG9hZA== -e PORTAL_CONFIG=unused')
            saved=[]; requests=[]
            def fake_cli(*args):
                requests.append(args[:2])
                if args[:2]==('search','templates'):
                    return [original] if args[2].startswith('hash_id=') else saved
                self.assertEqual(args[:2],('create','template'))
                def value(key): return args[args.index(key)+1]
                self.assertNotIn('--public',args)
                self.assertEqual(value('--image_tag'),'ubuntu_cli_22.04-2025-11-21')
                self.assertEqual(value('--disk_space'),'50')
                self.assertIn('vms_enabled=true',value('--search_params'))
                env=creator.environment_fields(value('--env'))
                self.assertNotIn('PORTAL_CONFIG',env)
                saved.append(dict(id=456,hash_id='core-hash',name='Vastgame Core VM',
                    image=value('--image'),tag=value('--image_tag'),runtype='ssh',private=True,ssh_direct=True,
                    recommended_disk_space=50,env=json.dumps(env),onstart=value('--onstart-cmd'),
                    extra_filters={'vms_enabled':{'eq':True}},creator_id=123))
                return {'success':True}
            with patch.dict(os.environ,XDG_CONFIG_HOME=tmp),patch.object(creator,'cli',fake_cli):
                creator.main(); creator.main()
            self.assertEqual(requests.count(('create','template')),1)
            self.assertEqual(selected.read_text(),'core-hash\n')
            self.assertEqual((cfg/'template_hash.before-core-vm').read_text(),'previous\n')
            self.assertEqual(selected.stat().st_mode & 0o777,0o600)

    def test_bad_readback_never_changes_selected_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=Path(tmp)/'vastgame'; cfg.mkdir(); (cfg/'template_hash').write_text('previous\n')
            original=dict(creator_id=123,env={'TS_AUTHKEY':'fixture','RCLONE_CONFIG_B64':'fixture'})
            wrong=dict(name='Vastgame Core VM',private=False)
            def fake_cli(*args): return [original] if args[2].startswith('hash_id=') else [wrong]
            with patch.dict(os.environ,XDG_CONFIG_HOME=tmp),patch.object(creator,'cli',fake_cli):
                with self.assertRaisesRegex(RuntimeError,'readback differs'): creator.main()
            self.assertEqual((cfg/'template_hash').read_text(),'previous\n')

    def test_environment_json_and_shell_formats_preserve_values(self):
        data={'TS_AUTHKEY':'fixture','RCLONE_CONFIG_B64':'abc==','VASTGAME_TEMPLATE_PROFILE':'core-v1'}
        self.assertEqual(creator.environment_fields(creator.options(data)),data)
        self.assertEqual(creator.environment_fields(json.dumps(data)),data)

    def test_pack_transmits_core_setup_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'start.sh'
            subprocess.run(['python3',str(ROOT/'src/bootstrap/pack.py'),str(ROOT/'src/bootstrap/start.sh'),str(output)],check=True)
            self.assertLess(output.stat().st_size,15360)
            payload=output.read_text().split("VASTGAME_BOOTSTRAP_B85' | xz -dc > \"$tmp\"\n",1)[1].split('\nVASTGAME_BOOTSTRAP_B85',1)[0]
            raw=lzma.decompress(base64.b85decode(payload))
            self.assertIn(b'prepare_core_vm() {',raw)
            self.assertTrue(raw.startswith(b'#!/usr/bin/env bash\nset -Eeuo pipefail\n'))
            self.assertEqual(raw.split(b'LOG=',1)[0].count(b'#!'),1)
            subprocess.run(['bash','-n'],input=raw,check=True)

    def test_failed_dependency_install_stops_before_gpu_or_service_changes(self):
        code='''set -Eeuo pipefail
source "$VASTGAME_TEST_CORE"
command() { return 1; }
timeout() { echo APT_FAILED; return 42; }
systemctl() { echo UNEXPECTED_SERVICE; }
prepare_core_vm
echo UNEXPECTED_READY
'''
        with tempfile.TemporaryDirectory() as tmp:
            helper=Path(tmp)/'core.sh'
            helper.write_text((ROOT/'src/bootstrap/core-vm.sh').read_text().replace(
                '/etc/apt/apt.conf.d/52vastgame-driver-stability', str(Path(tmp)/'driver-policy')))
            code=code.replace('command() { return 1; }', 'mkdir() { :; }\ncommand() { return 1; }')
            result=subprocess.run(['bash','-c',code],env=dict(os.environ,VASTGAME_TEST_CORE=str(helper)),capture_output=True,text=True)
        self.assertEqual(result.returncode,42,result.stdout+result.stderr)
        self.assertNotIn('UNEXPECTED_',result.stdout)


class CoreProvisioningTests(unittest.TestCase):
    def provision(self, prepared=False, available=True, devices=True):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'modprobe.d').mkdir()
            (root/'modeset').write_text('Y\n')
            helper=(ROOT/'src/bootstrap/core-vm.sh').read_text()
            for original,replacement in {
                '/sys/module/nvidia_drm/parameters/modeset':str(root/'modeset'),
                '/sys/module/nvidia_drm/refcnt':str(root/'refs'),
                '/etc/modprobe.d':str(root/'modprobe.d'),
                '/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg':str(root/'key.gpg'),
                '/etc/apt/sources.list.d/nvidia-container-toolkit.list':str(root/'repo.list'),
                '/dev/uinput':'/dev/null' if devices else str(root/'absent-input'),
                '/dev/uhid':'/dev/null' if devices else str(root/'absent-hid'),
                '/root/.ssh/authorized_keys':str(root/'absent-key'),
                '/etc/apt/apt.conf.d/52vastgame-driver-stability':str(root/'driver-policy'),
            }.items(): helper=helper.replace(original,replacement)
            stubs=r'''set -Eeuo pipefail
command() {
  if [[ "$1" == -v && ( "$2" == docker || "$2" == nvidia-ctk || "$2" == jq ) && "$INSTALLED" == 0 ]]; then return 1; fi
  builtin command "$@"
}
timeout() { shift; "$@"; }
apt-get() { printf '%s\n' "$*" >> "$CALLS"; if [[ "$*" == *'install -y'* ]]; then INSTALLED=1; fi; }
apt-cache() { [[ "$AVAILABLE" == 1 ]]; }
curl() { echo 'deb https://nvidia.github.io/libnvidia-container/stable/deb/amd64 /'; }
gpg() { cat >/dev/null; }
nvidia-ctk() { :; }
docker() { :; }
nvidia-smi() { :; }
modprobe() { return 1; }
systemctl() { :; }
chown() { :; }
chmod() { :; }
mkdir() { :; }
'''
            result=subprocess.run(['bash','-c',stubs+helper+'\nprepare_core_vm'],
                env=dict(os.environ,CALLS=str(root/'calls'),INSTALLED='1' if prepared else '0',AVAILABLE='1' if available else '0',
                         NVIDIA_CONTAINER_TOOLKIT_VERSION='1.20.1-1'),capture_output=True,text=True)
            calls=(root/'calls').read_text().splitlines() if (root/'calls').exists() else []
            return result,calls

    def test_missing_common_docker_toolkit_installs_together_after_one_update(self):
        result,calls=self.provision()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(sum(c.endswith('update') for c in calls),1)
        installs=[c for c in calls if 'install -y' in c]
        self.assertEqual(len(installs),1)
        self.assertIn('docker.io',installs[0]); self.assertIn('jq',installs[0])
        self.assertIn('nvidia-container-toolkit=1.20.1-1',installs[0])
        self.assertIn('DPkg::Lock::Timeout=600',installs[0])

    def test_unavailable_pin_fails_clearly_before_install(self):
        result,calls=self.provision(available=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('version 1.20.1-1 unavailable',result.stdout)
        self.assertFalse(any('install -y' in c for c in calls))

    def test_prepared_vm_runs_validation_without_apt(self):
        result,calls=self.provision(prepared=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(calls,[])

    def test_failed_modprobe_reports_actual_missing_devices(self):
        result,calls=self.provision(prepared=True,devices=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Virtual input devices missing',result.stdout)
        self.assertNotIn('dependencies ready',result.stdout)


class CoreGpuRuntimeTests(unittest.TestCase):
    def check(self, gpu=0, refresh=0):
        code='''set -Eeuo pipefail
source "$VASTGAME_TEST_CORE"
timeout() { shift; "$@"; }
nvidia-smi() { echo 'driver fixture'; return "$GPU_RESULT"; }
systemctl() { echo "SERVICE:$*"; return "$REFRESH_RESULT"; }
prepare_core_gpu_runtime
'''
        return subprocess.run(['bash','-c',code],env=dict(os.environ,
            VASTGAME_TEST_CORE=str(ROOT/'src/bootstrap/core-vm.sh'),
            GPU_RESULT=str(gpu),REFRESH_RESULT=str(refresh)),capture_output=True,text=True)

    def test_driver_error_reports_cause_before_cdi_refresh(self):
        result=self.check(gpu=1)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('VM GPU driver is not ready: driver fixture',result.stdout)
        self.assertNotIn('SERVICE:',result.stdout)

    def test_healthy_driver_refreshes_device_definitions(self):
        result=self.check()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('SERVICE:restart nvidia-cdi-refresh.service',result.stdout)

    def test_driver_policy_keeps_other_updates_enabled(self):
        source=(ROOT/'src/bootstrap/core-vm.sh').read_text()
        policy=source.split("<<'DRIVER_POLICY'",1)[1].split('\nDRIVER_POLICY',1)[0]
        self.assertIn('"^libnvidia-";',policy)
        self.assertNotIn('".*"',policy)
        self.assertNotIn('APT::Periodic',policy)


class CoreModesetTests(unittest.TestCase):
    def run_setup(self, initial='N', refs='0', load=True):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'config').mkdir()
            mode=root/'mode'; ref=root/'refs'; log=root/'calls'
            if initial is not None: mode.write_text(initial+'\n')
            ref.write_text(refs+'\n')
            helper=(ROOT/'src/bootstrap/core-vm.sh').read_text()
            helper=helper.replace('/sys/module/nvidia_drm/parameters/modeset',str(mode))
            helper=helper.replace('/sys/module/nvidia_drm/refcnt',str(ref))
            helper=helper.replace('/etc/modprobe.d',str(root/'config'))
            stubs=r'''set -Eeuo pipefail
modprobe() {
  printf '%s\n' "$*" >> "$CALLS"
  if [[ "$1" == -r ]]; then rm -f "$MODE"; return 0; fi
  if [[ "$LOAD_OK" == 1 ]]; then echo Y > "$MODE"; else return 42; fi
}
'''
            result=subprocess.run(['bash','-c',stubs+helper+'\nprepare_core_modeset'],
                env=dict(os.environ,CALLS=str(log),MODE=str(mode),LOAD_OK='1' if load else '0'),capture_output=True,text=True)
            calls=log.read_text().splitlines() if log.exists() else []
            config=(root/'config/vastgame-nvidia-drm.conf').read_text()
            return result,calls,config

    def test_unused_disabled_module_reloads_with_modeset(self):
        result,calls,config=self.run_setup()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(calls,['-r nvidia_drm','nvidia_drm modeset=1'])
        self.assertEqual(config,'options nvidia_drm modeset=1\n')

    def test_busy_module_is_not_unloaded_or_rebooted(self):
        result,calls,config=self.run_setup(refs='1')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(calls,[])
        self.assertIn('module is in use',result.stdout)

    def test_enabled_module_is_left_loaded(self):
        result,calls,config=self.run_setup(initial='Y')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(calls,[])

    def test_unloaded_module_loads_directly(self):
        result,calls,config=self.run_setup(initial=None)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(calls,['nvidia_drm modeset=1'])

    def test_load_failure_is_explicit_and_blocks_startup(self):
        result,calls,config=self.run_setup(initial=None,load=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Could not load NVIDIA DRM',result.stdout)
