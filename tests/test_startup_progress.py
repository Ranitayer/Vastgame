import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('startup_progress', Path(__file__).resolve().parents[1]/'src/client/startup_progress.py')
progress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(progress)

class StartupProgressTests(unittest.TestCase):
    def test_game_transfer_measures_the_whole_package_and_uses_fresh_throughput(self):
        state = progress.from_tasks({'tasks': {'game': {'state':'running', 'bytes':512, 'total':1024,
            'speed':256, 'updated':100, 'verified_parts':2, 'total_parts':10}}}, now=101)
        game = next(item for item in state['stages'] if item['id'] == 'game')
        self.assertEqual(game['percent'], 50)
        self.assertEqual(game['eta'], 2)
        self.assertEqual(game['total'], 1024)
        self.assertEqual(state['active'], 'game')

    def test_stale_unknown_and_completed_transfer_never_get_a_guessed_eta(self):
        for task in [{'state':'running','bytes':1,'total':10,'speed':3,'updated':80},
                     {'state':'running'}, {'state':'done','bytes':10,'total':10,'speed':3,'updated':100}]:
            state = progress.from_tasks({'tasks': {'game':task}}, now=101)
            game = next(item for item in state['stages'] if item['id'] == 'game')
            self.assertNotIn('eta', game)

    def test_game_start_confirmation_completes_all_required_stages(self):
        state = progress.milestone(progress.empty(), 'Game running')
        self.assertTrue(all(item['state'] == 'done' for item in state['stages']))
