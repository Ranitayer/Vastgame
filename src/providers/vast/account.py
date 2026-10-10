"""Expose only Vast's available account credit to the CLI and desktop."""
import json
import math
import subprocess
import sys


def account_balance(user):
    credit = user.get('credit') if isinstance(user, dict) else None
    if isinstance(credit, bool) or not isinstance(credit, (int, float)) or not math.isfinite(credit):
        raise ValueError('Vast returned an invalid account credit balance')
    return {'balance': {'usd': credit}}


def main():
    try:
        result = subprocess.run(['vastai', 'show', 'user', '--raw'],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError('Cannot read Vast account balance; check account access and retry')
        if len(result.stdout) > 65536:
            raise ValueError('Vast account response exceeded its size limit')
        print(json.dumps(account_balance(json.loads(result.stdout)), allow_nan=False))
    except subprocess.TimeoutExpired:
        print('Account balance request timed out; retry when connected', file=sys.stderr)
        return 1
    except (OSError, ValueError):
        # Never pass the raw account response, credentials or provider errors to the UI.
        print('Account balance unavailable; check Vast account access and retry', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
