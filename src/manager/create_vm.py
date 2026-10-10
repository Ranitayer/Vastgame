#!/usr/bin/env python3
"""Create a VM explicitly, including when the selected template defaults to Docker."""
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        raise HTTPError(request.full_url, code, 'Create request redirect refused', headers, fp)


def main():
    template_hash, offer, disk, label, startup_path = sys.argv[1:]
    if not offer.isdecimal() or int(offer) <= 0 or not disk.isdecimal() or int(disk) < 32:
        raise ValueError('Invalid offer or VM disk size')
    if not re.fullmatch(r'vastgame-[0-9]+', label):
        raise ValueError('Invalid unique launch label')
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    key = os.environ.get('VAST_API_KEY')
    if not key:
        key_file = config_home / 'vastai/vast_api_key'
        if not key_file.exists():
            key_file = Path.home() / '.vast_api_key'
        if not key_file.exists():
            raise ValueError('Vast API key is missing')
        key = key_file.read_text().strip()
    if not key:
        raise ValueError('Vast API key is missing')
    startup = Path(startup_path).read_text()
    payload = dict(client_id='me', vm=True, template_hash_id=template_hash,
                   disk=int(disk), label=label, onstart=startup, cancel_unavail=True)
    request = Request(f'https://console.vast.ai/api/v0/asks/{offer}/',
                      data=json.dumps(payload).encode(), method='PUT',
                      headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    # Never retry a rental request or forward its credentials on a redirect.
    # The shell's existing deadline/unique-label recovery handles uncertain results.
    try:
        with build_opener(NoRedirect).open(request, timeout=120) as response:
            result = json.load(response)
    except HTTPError as exc:
        try:
            error = json.loads(exc.read())
        except (ValueError, UnicodeError):
            error = {}
        if not isinstance(error, dict):
            error = {}
        if error.get('error') == 'no_such_ask' or exc.code in (404, 410):
            raise RuntimeError('Selected offer became unavailable') from None
        message = str(error.get('msg') or error.get('error') or exc.reason)
        message = message.replace(key, '[redacted]').replace(startup, '[redacted startup]')
        raise RuntimeError(f'Vast API rejected creation (HTTP {exc.code}): {message[:500]}') from None
    except URLError as exc:
        raise RuntimeError('Vast API connection failed: ' + str(exc.reason)) from None
    if not isinstance(result, dict):
        raise RuntimeError('Vast API returned an unexpected response')
    result.pop('instance_api_key', None)
    if result.get('success') is not True:
        if result.get('error') == 'no_such_ask':
            raise RuntimeError('Selected offer became unavailable')
        message = str(result.get('msg') or result.get('error') or 'unknown reason')
        message = message.replace(key, '[redacted]').replace(startup, '[redacted startup]')
        raise RuntimeError('Vast API rejected creation: ' + message[:500]) from None
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(1)
