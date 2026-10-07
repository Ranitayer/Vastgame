from support import cli_source
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


class MetadataPublicationTests(unittest.TestCase):
    def test_windows_manifest_without_source_is_published_and_corruption_blocks_rental(self):
        cli = cli_source()
        function = cli[cli.index('publish_runtime() {'):cli.index('\n# ============================================================\n# CONNECT / LOGS')]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'runtime').mkdir()
            # The bundle itself can be empty; validation imports the real runtime.
            for file in (Path(__file__).resolve().parents[1] / 'src/runtime').glob('*.py'):
                (root / 'runtime' / file.name).write_bytes(file.read_bytes())
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps(dict(schema=1, id='fixture', name='Game',
                game=dict(executable='Game.exe'), package=dict(archive='games/fixture/v1/game-v1.tar.zst'))))
            (root / 'selected').write_text('fixture')
            for corrupt in (False, True):
                with self.subTest(corrupt=corrupt):
                    marker = root / 'rented'
                    marker.unlink(missing_ok=True)
                    script = root / 'publish.sh'
                    script.write_text('set -euo pipefail\n' + f'CFGDIR={shlex.quote(str(root))}\nSTATEDIR="$CFGDIR"\nRUNTIME_DIR="$CFGDIR/runtime"\nSELECTED_GAME_FILE="$CFGDIR/selected"\nREMOTE_ROOT=mock:VastGaming\n' + '''
die() { echo "$*" >&2; exit 1; }
valid_game_id() { [[ "$1" == fixture ]]; }
game_manifest() { echo "$CFGDIR/manifest.json"; }
rclone() {
    local source="$2" target="$3"
    [[ "$source" != *:* ]] || source="$CFGDIR/remote-${source##*/}"
    [[ "$target" != *:* ]] || target="$CFGDIR/remote-${target##*/}"
    cp "$source" "$target" || return 1
''' + ('[[ "$target" != *.manifest.verify ]] || echo corrupt > "$target"\n' if corrupt else '') + '''
    return 0
}
''' + function + '\npublish_runtime\ntouch "$CFGDIR/rented"\n')
                    result = subprocess.run(['bash', str(script)], capture_output=True, text=True, timeout=20)
                    if corrupt:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(marker.exists())
                        self.assertIn('readback differs', result.stderr)
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertTrue(marker.exists())
                        self.assertEqual(next(p for p in root.glob('remote-*.json') if p.read_bytes() == manifest.read_bytes()).read_bytes(), manifest.read_bytes())


if __name__ == '__main__': unittest.main()
