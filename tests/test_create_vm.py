import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('create_vm', ROOT/'src/manager/create_vm.py')
create_vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(create_vm)


class CreateVMTests(unittest.TestCase):
    def test_template_launch_explicitly_requests_vm_without_image_override(self):
        with tempfile.TemporaryDirectory() as directory:
            startup = Path(directory)/'startup.sh'
            startup.write_text('#!/bin/sh\ntrue\n')
            with patch.object(create_vm.sys, 'argv', ['create_vm.py', '-', 'template', '123', '60', 'vastgame-123', str(startup)]), \
                 patch.dict(create_vm.os.environ, {'VAST_API_KEY': 'fixture'}), \
                 patch.object(create_vm, 'build_opener') as opener, \
                 patch('sys.stdout', new_callable=io.StringIO):
                opener.return_value.open.return_value.__enter__.return_value = io.StringIO('{"success":true,"new_contract":123}')
                create_vm.main()
                request = opener.return_value.open.call_args.args[0]
                payload = json.loads(request.data)
                self.assertIs(payload['vm'], True)
                self.assertEqual(payload['template_hash_id'], 'template')
                self.assertNotIn('image', payload)
                self.assertEqual(opener.return_value.open.call_count, 1)
