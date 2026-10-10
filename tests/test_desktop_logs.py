import json
from pathlib import Path
import subprocess
import unittest


class DesktopLogTests(unittest.TestCase):
    def test_full_console_output_keeps_details_indentation_and_repeated_lines(self):
        module = (Path(__file__).resolve().parents[1]/'desktop/src/session/logs.ts').as_uri()
        script = 'import {formatLog, appendLogs} from '+json.dumps(module)+';'+'''
const raw = ['━━━━━━━━━━', 'VASTGAME | DRIVE | Game 50% | spinner', '[VASTGAME_GAME_REQUESTED]',
 'Stage 1/3 — Creating Vast VM', 'Quote verified: 0.14472222222222222 USD/h with 89 GB allocated',
 '⚠ SSH unavailable; trying another endpoint', '[VM_UNSUPPORTED] This offer does not support virtual machines',
 '✓ Final Google Drive state backup complete', 'Bootstrap payload: 32497 bytes -> 13833 bytes packed',
 '  File "/tmp/vastgame-bootstrap.sh", line 90', '{"success":true,"new_contract":55099473}',
 'Ctrl+Shift+Q stream menu · Alt+Tab local windows'];
const rows = raw.map(line => formatLog(line)).filter(Boolean);
process.stdout.write(JSON.stringify({raw, rows, repeated: appendLogs(rows, [rows.at(-1)])}));
'''
        result = subprocess.check_output(['node', '--experimental-strip-types', '--input-type=module', '-e', script], text=True)
        value = json.loads(result)
        self.assertEqual([row['message'] for row in value['rows']], value['raw'])
        self.assertEqual([row['level'] for row in value['rows'][5:8]], ['warning', 'error', 'success'])
        self.assertEqual(value['repeated'], [*value['rows'], value['rows'][-1]])
        self.assertTrue(all('time' not in row and 'scope' not in row for row in value['rows']))

    def test_structured_errors_keep_every_field(self):
        module = (Path(__file__).resolve().parents[1]/'desktop/src/session/logs.ts').as_uri()
        raw = '[VASTGAME_ERROR]'+json.dumps(dict(code='DISK_INSUFFICIENT', message='Needs 145 GB; rig has 120 GB', required=145, available=120))
        script = 'import {formatLog} from '+json.dumps(module)+'; process.stdout.write(JSON.stringify(formatLog('+json.dumps(raw)+')));'
        row = json.loads(subprocess.check_output(['node', '--experimental-strip-types', '--input-type=module', '-e', script], text=True))
        self.assertEqual(row['message'], raw)
        self.assertEqual(row['level'], 'error')
