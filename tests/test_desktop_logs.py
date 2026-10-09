import json
from pathlib import Path
import subprocess
import unittest


class DesktopLogTests(unittest.TestCase):
    def test_activity_keeps_errors_and_stages_without_console_noise(self):
        module = (Path(__file__).resolve().parents[1]/'desktop/src/session/logs.ts').as_uri()
        script = 'import {importantLog, appendLogs} from '+json.dumps(module)+';'+'''
const raw = ['━━━━━━━━━━', 'VASTGAME | DRIVE | Game 50% | spinner', '[VASTGAME_GAME_REQUESTED]',
 'Stage 1/3 — Creating Vast VM', 'Quote verified: 0.14472222222222222 USD/h with 89 GB allocated',
 '⚠ SSH unavailable; trying another endpoint', '[VM_UNSUPPORTED] This offer does not support virtual machines',
 '✓ Final Google Drive state backup complete'];
const rows = raw.map(line => importantLog(line, 1900000000000)).filter(Boolean);
process.stdout.write(JSON.stringify({rows, repeated: appendLogs(rows, [rows.at(-1)])}));
'''
        result = subprocess.check_output(['node', '--experimental-strip-types', '--input-type=module', '-e', script], text=True)
        value = json.loads(result)
        self.assertEqual(len(value['rows']), 5)
        self.assertEqual(value['rows'][1]['message'], 'Quote $0.1447/h · 89 GB disk')
        self.assertEqual([row['level'] for row in value['rows'][-3:]], ['warning', 'error', 'success'])
        self.assertEqual(value['rows'], value['repeated'])

    def test_structured_errors_show_the_code_and_explanation(self):
        module = (Path(__file__).resolve().parents[1]/'desktop/src/session/logs.ts').as_uri()
        raw = '[VASTGAME_ERROR]'+json.dumps(dict(code='DISK_INSUFFICIENT', message='Needs 145 GB; rig has 120 GB', required=145, available=120))
        script = 'import {importantLog} from '+json.dumps(module)+'; process.stdout.write(JSON.stringify(importantLog('+json.dumps(raw)+')));'
        row = json.loads(subprocess.check_output(['node', '--experimental-strip-types', '--input-type=module', '-e', script], text=True))
        self.assertEqual(row['message'], '[DISK_INSUFFICIENT] Needs 145 GB; rig has 120 GB')
        self.assertEqual(row['level'], 'error')
