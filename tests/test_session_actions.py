"""Offline checks for history replay: exact rig, price budget and no accidental rental."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/client'))
import session_actions as actions
from offer_quote import OfferError


class ReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manifest = Path(temporary.name)/'manifest.json'
        self.manifest.write_text('{}')
        self.record = dict(id='vastgame-123', game_id='fixture', hourly_price_usd='0.20',
                           rig=dict(machine_id=42, gpu_name='RTX_3090'))
        self.game = dict(id='fixture', name='Fixture')

    def offer(self):
        return dict(id=8, machine_id=42, gpu_name='RTX_3090', dph_total=0.21)

    def test_replay_selects_only_same_machine_and_gpu_under_ten_percent(self):
        offers = [self.offer(), dict(id=9, machine_id=99, gpu_name='RTX_3090', dph_total=0.10),
                  dict(id=10, machine_id=42, gpu_name='RTX_5090', dph_total=0.10)]
        with patch.object(actions, 'required_disk_gb', return_value=89), patch.object(actions, 'fetch_offers', return_value=offers) as fetch, patch.object(actions, 'validate') as validate:
            result = actions.candidate(self.record, self.game, self.manifest)
        self.assertEqual(result['rig']['id'], 8)
        self.assertAlmostEqual(result['max_price'], 0.22)
        fetch.assert_called_once_with(89, 42, timeout=45)
        validate.assert_called_once_with(offers[0], 89, result['max_price'])

    def test_missing_old_price_or_identity_never_searches_or_rents(self):
        with patch.object(actions, 'fetch_offers') as fetch:
            with self.assertRaises(OfferError): actions.candidate(dict(self.record, hourly_price_usd=None), self.game, self.manifest)
            with self.assertRaises(OfferError): actions.candidate(dict(self.record, rig={}), self.game, self.manifest)
        fetch.assert_not_called()

    def test_failed_disk_or_price_validation_cannot_supply_replacement(self):
        with patch.object(actions, 'required_disk_gb', return_value=89), patch.object(actions, 'fetch_offers', return_value=[self.offer()]), patch.object(actions, 'validate', side_effect=OfferError('PRICE_INCREASED', 'Price increased')):
            with self.assertRaises(OfferError) as caught: actions.candidate(self.record, self.game, self.manifest)
        self.assertEqual(caught.exception.error['code'], 'PREVIOUS_RIG_UNAVAILABLE')

    def test_lookup_failure_and_another_rental_never_search_or_create(self):
        with patch.object(actions.history, 'read', return_value=self.record), patch.object(actions.desktop, 'instance_rows', side_effect=ValueError('API unavailable')), patch.object(actions, 'candidate') as candidate:
            with self.assertRaises(ValueError): actions.prepare('vastgame-123')
            candidate.assert_not_called()
        with patch.object(actions.history, 'read', return_value=self.record), patch.object(actions.desktop, 'instance_rows', return_value=[dict(id=99, label='vastgame-999')]), patch.object(actions.desktop, 'current', return_value=None), patch.object(actions, 'candidate') as candidate:
            with self.assertRaises(OfferError): actions.prepare('vastgame-123')
            candidate.assert_not_called()

    def test_shutdown_of_absent_rig_does_not_quote_or_rent(self):
        record = dict(self.record, instance_id='123')
        with patch.object(actions.history, 'read', return_value=record), patch.object(actions.history, 'destroyed') as destroyed, patch.object(actions.desktop, 'instance_rows', return_value=[]), patch.object(actions.desktop, 'current', return_value=None), patch.object(actions, 'candidate') as candidate:
            self.assertEqual(actions.prepare('vastgame-123', shutdown=True), dict(launch=None))
            destroyed.assert_called_once_with('123', 'vastgame-123')
            candidate.assert_not_called()


if __name__ == '__main__': unittest.main()
