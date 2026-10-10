import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('account', Path(__file__).resolve().parents[1]/'src/providers/vast/account.py')
account = importlib.util.module_from_spec(spec)
spec.loader.exec_module(account)


class AccountBalanceTests(unittest.TestCase):
    def test_only_available_credit_is_exposed_without_rounding(self):
        user = {'credit': 0.27222205, 'balance': 12, 'email': 'private', 'ssh_key': 'private'}
        self.assertEqual(account.account_balance(user), {'balance': {'usd': 0.27222205}})
        self.assertEqual(account.account_balance({'credit': -0.01}), {'balance': {'usd': -0.01}})

    def test_missing_or_invalid_credit_never_looks_like_zero(self):
        for value in (None, [], {}, {'credit': True}, {'credit': '0.27'}, {'credit': float('nan')}, {'credit': float('inf')}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                account.account_balance(value)
