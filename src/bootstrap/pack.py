from pathlib import Path
import base64
import lzma
import sys
import shlex
import os
import json
import ipaddress

src = Path(sys.argv[1])
dst = Path(sys.argv[2])

# Drop standalone shell/Python comments from the transport only. Source stays readable.
# No payload line begins with '#' inside a multiline data string in this bootstrap.
configuration = Path(os.environ.get("VASTGAME_BOOTSTRAP_CONFIG", ""))
settings = json.loads(configuration.read_text()) if configuration.is_file() else {}
if not isinstance(settings, dict) or set(settings) - {"TS_AUTHKEY", "RCLONE_CONFIG_B64"} or any(not isinstance(v, str) for v in settings.values()):
    raise ValueError("Invalid private bootstrap configuration")
force = os.environ.get('VASTGAME_FORCE_ROUTE', '0')
if force not in ('0', '1'):
    raise ValueError('Invalid force-route policy')
client = os.environ.get('VASTGAME_CLIENT_TSIP', '')
if client and ipaddress.ip_address(client) not in ipaddress.ip_network('100.64.0.0/10'):
    raise ValueError('Invalid client Tailscale address')
prefix = '#!/usr/bin/env bash\nset -Eeuo pipefail\n'
prefix += "".join(f"export {key}={shlex.quote(value)}\n" for key, value in settings.items())
prefix += f'export VASTGAME_FORCE_ROUTE={force}\nexport VASTGAME_CLIENT_TSIP={shlex.quote(client)}\n'
prefix += '\n'.join(src.with_name('core-vm.sh').read_text().splitlines()[1:]) + '\n'
raw = (prefix + "\n".join(line for line in src.read_text().replace("__VASTGAME_RUNTIME_SHA__", os.environ.get("RUNTIME_SHA", "")).splitlines()[2:]
                 if not line.lstrip().startswith("#") or line.startswith("#!")) + "\n").encode()

compressed = lzma.compress(raw, preset=9)

payload = base64.b64encode(compressed).decode("ascii")

lines = payload

wrapper = f"""#!/bin/sh
set -eu

export VASTGAME_LAUNCH_LABEL={shlex.quote(sys.argv[3] if len(sys.argv) > 3 else "")}
export VASTGAME_MACHINE_ID={shlex.quote(sys.argv[4] if len(sys.argv) > 4 else "")}
export VASTGAME_GAME_MANIFEST={shlex.quote(os.environ.get('GAME_MANIFEST_PATH', ''))}
export VASTGAME_GAME_MANIFEST_SHA={shlex.quote(os.environ.get('GAME_MANIFEST_SHA', ''))}
export VASTGAME_GAME_ID={shlex.quote(sys.argv[5] if len(sys.argv) > 5 else "")}
tmp=/tmp/vastgame-bootstrap.sh

command -v xz >/dev/null || {{ echo 'Bootstrap requires xz'; exit 1; }}
base64 -d <<'VASTGAME_BOOTSTRAP_B64' | xz -dc > "$tmp"
{lines}
VASTGAME_BOOTSTRAP_B64

chmod 700 "$tmp"
exec /bin/bash "$tmp"
"""

descriptor = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.fchmod(descriptor, 0o600)
with os.fdopen(descriptor, 'w') as output:
    output.write(wrapper)
