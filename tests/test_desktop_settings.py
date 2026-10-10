import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/client'))
import desktop_settings as settings
from stream_settings import read, resolve


class DesktopSettingsTests(unittest.TestCase):
    def test_reset_restores_shared_platform_defaults_and_repairs_invalid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp); stream = config/'stream.json'
            stream.write_text('{broken')
            (config/'host_preferences.json').write_text('{also broken')
            result = settings.preferences(config, stream, windows=True, reset=True)
            self.assertEqual(result['settings']['stream'], read(config/'missing.json', windows=True))
            self.assertEqual(result['settings']['hosts'], settings.DEFAULTS)
            self.assertEqual(read(stream, windows=True)['video_codec'], 'AV1')
            self.assertEqual(settings.read_hosts(config), settings.DEFAULTS)

    def test_combined_save_validates_both_groups_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp); stream = config/'stream.json'
            stream.write_text('{"fps":60}')
            with self.assertRaises(ValueError):
                settings.preferences(config, stream, patch={'stream': {'fps': 120}, 'hosts': {'min_ram_gb': -1}})
            self.assertEqual(stream.read_text(), '{"fps":60}')
            self.assertFalse((config/'host_preferences.json').exists())

    def test_combined_save_restores_stream_if_host_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp); stream = config/'stream.json'; hosts = config/'host_preferences.json'
            stream.write_text('{"fps":60}'); hosts.write_text('{}')
            original_write = settings.atomic_write
            def fail_host(path, data):
                if path == hosts: raise OSError('Host disk write failed')
                return original_write(path, data)
            with patch.object(settings, 'atomic_write', side_effect=fail_host), self.assertRaises(OSError):
                settings.preferences(config, stream, patch={'stream': {'fps': 120}, 'hosts': {'verified_only': True}})
            self.assertEqual(stream.read_text(), '{"fps":60}')
            self.assertEqual(hosts.read_text(), '{}')

    def test_new_options_reach_moonlight_without_replacing_other_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp); stream = config/'stream.json'
            stream.write_text(json.dumps({'moonlight_options': {'hdr': True, 'audio-on-host': True}}))
            settings.preferences(config, stream, patch={'stream': {'video_decoder': 'software',
                'display_mode': 'borderless', 'moonlight_options': {'vsync': False, 'frame-pacing': True,
                'yuv444': True, 'audio-config': '5.1-surround'}}, 'hosts': {'verified_only': True}})
            args = resolve(read(stream), '1920x1080', 60)['args']
            for key, value in [('--video-decoder', 'software'), ('--display-mode', 'borderless'),
                               ('--audio-config', '5.1-surround')]:
                self.assertEqual(args[args.index(key) + 1], value)
            for option in ['--no-vsync', '--frame-pacing', '--yuv444', '--hdr', '--audio-on-host']:
                self.assertIn(option, args)
            self.assertTrue(settings.read_hosts(config)['verified_only'])

    def test_stream_save_reaches_moonlight_and_preserves_unrelated_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)
            path = config / 'stream.json'
            path.write_text(json.dumps(dict(display_mode='windowed', video_decoder='software',
                                           moonlight_options={'vsync': False})))
            settings.preferences(config, path, patch={'stream': dict(video_codec='HEVC', fps=144,
                                  resolution='2560x1440', bitrate_mbps=42)})
            saved = read(path)
            args = resolve(saved, '1920x1080', 60)['args']
            self.assertEqual(saved['display_mode'], 'windowed')
            self.assertEqual(saved['video_decoder'], 'software')
            for key, value in [('--bitrate', '42000'), ('--resolution', '2560x1440'),
                               ('--fps', '144'), ('--video-codec', 'HEVC')]:
                self.assertEqual(args[args.index(key) + 1], value)
            self.assertIn('--no-vsync', args)

    def test_invalid_settings_never_replace_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp); stream = config / 'stream.json'
            stream.write_text('{"fps":60}')
            for patch in [{'stream': {'fps': True}}, {'stream': {'resolution': '--host another'}},
                          {'stream': {'args': ['--quit-after']}}, {'hosts': {'country': ['US']}},
                          {'hosts': {'verified_only': 'true'}}, {'hosts': {'min_ram_gb': -1}},
                          {'hosts': {'spending_limit_usd': float('nan')}}]:
                with self.subTest(patch=patch), self.assertRaises(ValueError):
                    settings.preferences(config, stream, patch=patch)
                self.assertEqual(stream.read_text(), '{"fps":60}')
            target = config / 'host_preferences.json'; target.symlink_to(stream)
            with self.assertRaises(ValueError):
                settings.preferences(config, stream, patch={'hosts': {'verified_only': True}})
            self.assertEqual(stream.read_text(), '{"fps":60}')

    def test_country_ranking_and_inactive_spending_limit(self):
        self.assertEqual(len(settings.COUNTRIES), 249)
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)
            settings.preferences(config, config/'stream.json', patch={'hosts': {'country': 'FR',
                                  'preferred_gpu': 'RTX 3060', 'spending_limit_usd': 0.1}})
            preferences = settings.ranking(config)
            self.assertGreater(preferences['country_points']['FR'], preferences['country_points']['US'])
            self.assertGreater(preferences['country_points']['DE'], preferences['country_points']['AU'])
            base = dict(vms_enabled=True, gpu_ram=8192, cpu_ram=16384,
                        cpu_cores_effective=4, dph_total=0.2, inet_down=200, inet_up=100,
                        gpu_name='RTX 3060', geolocation='France, FR', verification='verified')
            offers = [dict(base, id=1), dict(base, id=2, verification='unverified'),
                      dict(base, id=3, gpu_ram=7168), dict(base, id=4, cpu_ram=15360),
                      dict(base, id=5, inet_down=199), dict(base, id=6, inet_up=99),
                      dict(base, id=7, verification='', verified=True),
                      dict(base, id=8, geolocation='Unknown')]
            preferences.update(verified_only=True, min_vram_gb=8, min_ram_gb=16,
                               min_download_mbps=200, min_upload_mbps=100)
            result = subprocess.run(['jq', '--argjson', 'max', '100', '--argjson', 'cap', '1e99',
                '--argjson', 'value_cap', '0.7', '--argjson', 'host_preferences', json.dumps(preferences),
                '--arg', 'selected_game', '', '--arg', 'native_resolution', '1920x1080',
                '--argjson', 'native_fps', '60', '--slurpfile', 'hist', '/dev/null',
                '-L', str(ROOT/'src/providers/vast'), '-f', str(ROOT/'src/providers/vast/rank.jq')],
                input=json.dumps(offers), capture_output=True, text=True, check=True)
            ranked = json.loads(result.stdout)
            self.assertEqual({row['id'] for row in ranked}, {1, 7, 8})
            self.assertTrue(all(row['_vg']['preference'] == 5 for row in ranked))
            self.assertTrue(all(row['dph_total'] > preferences['spending_limit_usd'] for row in ranked))
