"""The shared safe VM disk requirement, in decimal GB."""
import json
import math
from pathlib import Path
import sys


def required_disk_gb(manifest):
    package = manifest.get('package', {})
    archive, installed = package.get('size'), package.get('unpacked_bytes')
    if not all(type(size) is int and size > 0 for size in (archive, installed)):
        raise ValueError('Package the game first: archive and installed sizes are required')
    parts = package.get('parts', [])
    if not isinstance(parts, list) or any(not isinstance(part, dict) or type(part.get('size')) is not int or part['size'] <= 0 for part in parts):
        raise ValueError('Invalid package part sizes')
    scratch = sum(sorted((part['size'] for part in parts), reverse=True)[:8]) if parts else archive
    reserve = 35 * 1024**3  # guest, images, Proton, prefix and save state
    return max(60, math.ceil(((installed + scratch) * 1.15 + reserve) / 10**9))


if __name__ == '__main__':
    try:
        print(required_disk_gb(json.loads(Path(sys.argv[1]).read_text())))
    except (OSError, ValueError, TypeError, IndexError) as exc:
        raise SystemExit(str(exc))
