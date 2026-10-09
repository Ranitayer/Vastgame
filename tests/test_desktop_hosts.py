import importlib.util
import json
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('desktop_hosts', ROOT / 'src/providers/vast/desktop_hosts.py')
hosts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hosts)


class DesktopHosts(unittest.TestCase):
    def test_summary_preserves_cli_eligibility_and_exposes_only_public_fields(self):
        base = dict(dph_total=1.25, gpu_ram=8192, cpu_name='CPU',
                    geolocation='USA, US', machine_id=1,
                    api_key='private', public_ipaddr='private', _vg={'score': 81.2})
        names = ['RTX_4090', 'RTX_4000Ada', 'RTX_A6000', 'Tesla_T4']
        offers = [dict(base, id=i+1, gpu_name=name) for i, name in enumerate(names)]
        # Eligibility and history penalties belong to rank_host_offers, not this serializer.
        result = hosts.summarize(offers)
        self.assertEqual([h['id'] for h in result], [1, 2, 3, 4])
        self.assertEqual(result[0]['score'], 81.2)
        self.assertTrue(all('api_key' not in h and 'public_ipaddr' not in h
                            and '_vg' not in h for h in result))
        self.assertEqual(hosts.summarize([dict(base, id=0), dict(base, id=5, dph_total=float('nan'))]), [])

    def test_uncapped_browsing_preserves_shared_value_scale(self):
        offers = [dict(id=i, gpu_name='RTX 4090', vms_enabled=True,
                       gpu_ram=24576, cpu_cores_effective=8, dph_total=price,
                       geolocation='Spain, ES') for i, price in ((1, 0.3), (2, 1.2))]
        def ranked(cap):
            result = subprocess.run(['jq', '--argjson', 'max', '100',
                '--argjson', 'cap', str(cap), '--argjson', 'value_cap', '0.7',
                '--arg', 'selected_game', 'fixture', '--arg', 'native_resolution', '1920x1080',
                '--argjson', 'native_fps', '60', '--slurpfile', 'hist', '/dev/null',
                '-L', str(ROOT / 'src/providers/vast'), '-f', str(ROOT / 'src/providers/vast/rank.jq')],
                input=json.dumps(offers), text=True, capture_output=True, check=True)
            return {offer['id']: offer['_vg']['score'] for offer in json.loads(result.stdout)}
        launch, browse = ranked(0.7), ranked(1e99)
        self.assertEqual(set(launch), {1})
        self.assertEqual(set(browse), {1, 2})
        self.assertEqual(launch[1], browse[1])

    def test_both_views_request_the_shared_explicit_offer_ceiling(self):
        provider = (ROOT / 'src/manager/provider.sh').read_text()
        self.assertIn('--limit 10000', provider)
        for file in ('commands.sh', 'hosts.sh'):
            source = (ROOT / 'src/manager' / file).read_text()
            self.assertIn('search_host_offers "$query"', source)
