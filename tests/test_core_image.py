import json
import importlib.util
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/runtime'))
import prepare_game


class CoreImageTests(unittest.TestCase):
    def test_guest_preparation_uses_dependency_installer_not_live_gpu_preflight(self):
        guest=(ROOT/'packaging/core-vm/guest.sh').read_text()
        self.assertIn('install_core_dependencies',guest)
        self.assertNotIn('prepare_core_vm',guest)
        self.assertIn('/opt/vastgame/prepare-game.sh',guest)
        self.assertIn("seed/'share/pga.db'",guest)
        self.assertIn('cleanup\ntrap - EXIT',guest)
        dockerfile=(ROOT/'packaging/core-vm/Dockerfile').read_text()
        self.assertIn('COPY ubuntu.img /root/images/ubuntu.img',dockerfile)
        self.assertNotIn('ENTRYPOINT',dockerfile)
        for file in ['build.sh','guest.sh']:
            subprocess.run(['bash','-n',str(ROOT/'packaging/core-vm'/file)],check=True)

    def test_prebuilt_runner_is_validated_and_custom_runners_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'fixture';profile.mkdir()
            proton=root/'GE-Proton';proton.mkdir();(proton/'proton').write_text('fixture')
            env={'PROTONPATH':str(proton),'UMU_RUNTIME_UPDATE':'0'}
            (profile/'runtime-seed.json').write_text(json.dumps(env))
            manifest={'id':'fixture','runner':{'version':'ge-proton'}}
            self.assertEqual(prepare_game.runtime_seed_environment(manifest,root),env)
            manifest['runner']['version']='custom-wine'
            self.assertEqual(prepare_game.runtime_seed_environment(manifest,root),{})
            manifest['runner']['version']='ge-proton';(proton/'proton').unlink()
            with self.assertRaisesRegex(RuntimeError,'cache is incomplete'):
                prepare_game.runtime_seed_environment(manifest,root)

    def test_no_prebuilt_seed_preserves_existing_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(prepare_game.runtime_seed_environment({'id':'fixture'},Path(tmp)),{})


class WrapperFlattenTests(unittest.TestCase):
    def test_launch_configuration_is_preserved_in_import_options(self):
        spec=importlib.util.spec_from_file_location('flatten_core',ROOT/'packaging/core-vm/flatten.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        config={'Env':['PATH=/usr/local/cuda/bin:/usr/bin','NVIDIA_VISIBLE_DEVICES=all'],
                'Entrypoint':['/root/kaalia-vm-supervisor'],'Cmd':None,'WorkingDir':'/root',
                'Labels':{'fixture':'hello world'}}
        options=module.changes(config)
        self.assertIn('ENTRYPOINT ["/root/kaalia-vm-supervisor"]',options)
        self.assertIn('WORKDIR "/root"',options)
        self.assertIn('ENV NVIDIA_VISIBLE_DEVICES="all"',options)
        with self.assertRaisesRegex(ValueError,'hooks/volumes'):
            module.changes(dict(config,Volumes={'/data':{}}))
