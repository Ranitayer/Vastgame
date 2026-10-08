import importlib.util
import json
from pathlib import Path
import tempfile
import os
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('stream_settings', ROOT/'src/client/stream_settings.py')
settings=importlib.util.module_from_spec(spec); spec.loader.exec_module(settings)


class StreamSettingsTests(unittest.TestCase):
    def test_streamedit_preserves_invalid_file_so_user_can_repair_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); config=root/'stream.json'; config.write_text('{broken json')
            editor=root/'editor'; editor.write_text('#!/bin/sh\nprintf "%s" "$1"\n'); editor.chmod(0o755)
            code=f'''source "{ROOT}/src/manager/client.sh"
CFGDIR="$FIXTURE_DIR"
die() {{ echo "$*" >&2; exit 1; }}
edit_stream_settings
'''
            result=subprocess.run(['bash','-e','-u','-c',code],env=dict(os.environ,
                FIXTURE_DIR=str(root),EDITOR=str(editor),VISUAL='',VASTGAME_WINDOWS='0'),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(result.stdout.endswith(str(config)))
            self.assertEqual(config.read_text(),'{broken json')

    def test_streamedit_creates_defaults_without_cloud_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            code=f'''source "{ROOT}/src/manager/client.sh"
CFGDIR="$FIXTURE_DIR"
CLIENT_DIR="{ROOT}/src/client"
die() {{ echo "$*" >&2; exit 1; }}
edit_stream_settings
'''
            result=subprocess.run(['bash','-e','-u','-c',code],env=dict(os.environ,
                FIXTURE_DIR=str(root),EDITOR='true',VISUAL='',VASTGAME_WINDOWS='0'),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads((root/'stream.json').read_text())['resolution'],'native')

    def test_missing_config_follows_native_screen_and_platform_codec(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=settings.read(Path(tmp)/'missing.json',windows=True)
            resolved=settings.resolve(config,'2944x1840','90')
            self.assertEqual(resolved['resolution'],'2944x1840')
            self.assertEqual(resolved['fps'],90)
            self.assertEqual(resolved['video_codec'],'AV1')
            self.assertNotIn('--bitrate',resolved['args'])
            self.assertIn('--no-absolute-mouse',resolved['args'])

    def test_custom_targets_and_false_options_preserve_user_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'stream.json'
            path.write_text(json.dumps(dict(resolution='1920x1080',fps=60,bitrate_mbps=30,
                video_codec='HEVC',moonlight_options={'vsync':False,'performance-overlay':False})))
            resolved=settings.resolve(settings.read(path,windows=True),'3840x2160','120')
            self.assertEqual(resolved['fps'],60)
            self.assertEqual(resolved['resolution'],'1920x1080')
            args=resolved['args']
            self.assertEqual(args[args.index('--bitrate')+1],'30000')
            self.assertEqual(args[args.index('--video-codec')+1],'HEVC')
            self.assertIn('--no-vsync',args)
            self.assertIn('--no-performance-overlay',args)
            self.assertNotIn('--performance-overlay',args)

    def test_invalid_values_and_argument_injection_are_rejected(self):
        invalid=[{'fps':True},{'fps':0},{'bitrate_mbps':-1},
                 {'resolution':'1920x1080; echo bad'},{'video_codec':['AV1']},
                 {'moonlight_options':{'hdr':'false'}},
                 {'moonlight_options':{'host':'other-vm'}},{'extra_args':['--quit-after']}]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'stream.json'
            for data in invalid:
                with self.subTest(data=data):
                    path.write_text(json.dumps(data))
                    with self.assertRaises(ValueError): settings.read(path)
