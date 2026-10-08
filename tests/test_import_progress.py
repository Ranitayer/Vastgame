import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/client'))
from import_progress import Progress
import package_publish


class Terminal(io.StringIO):
    def isatty(self): return True


class ImportProgressTests(unittest.TestCase):
    def test_terminal_heartbeat_is_100ms_independent_of_byte_updates(self):
        display=Progress(Terminal())
        with patch.object(display, 'render') as render, patch.object(display.stop, 'wait', side_effect=[False, True]) as wait:
            display.refresh()
        self.assertEqual(wait.call_args_list[0].args, (0.1,))
        self.assertEqual(render.call_count, 2)

    def test_resumed_bytes_do_not_inflate_speed(self):
        display=Progress(Terminal())
        with patch('import_progress.time.monotonic', return_value=10):
            display.phase('Downloading', 20*1024**2, 10*1024**2)
        display.advance(2*1024**2)
        line=display.line(11)
        self.assertIn('60.0%',line)
        self.assertIn('2.0 MiB/s',line)
        self.assertIn('ETA ~0m 04s',line)

    def test_upload_percent_and_eta_cover_the_entire_measured_game(self):
        display=Progress(Terminal())
        with patch('import_progress.time.monotonic',return_value=10):
            display.begin_upload(1000*1024**2)
        display.part('part-00000',100*1024**2)
        display.upload('part-00000',50*1024**2)
        line=display.line(11)
        self.assertIn('5.0%',line)
        self.assertNotIn('50.0%',line)
        self.assertIn('ETA ~0m 19s',line)
        self.assertNotIn('queued',line)

    def test_reused_upload_receipts_do_not_inflate_transfer_speed(self):
        display=Progress(Terminal())
        with patch('import_progress.time.monotonic',return_value=10):
            display.begin_upload(100*1024**2)
        display.part('cached',40*1024**2); display.verify('cached')
        display.part('new',60*1024**2); display.upload('new',10*1024**2)
        line=display.line(11)
        self.assertIn('50.0%',line)
        self.assertIn('10.0 MiB/s',line)
        self.assertIn('ETA ~0m 05s',line)

    def test_uploaded_bytes_wait_for_verification_without_a_false_zero_second_eta(self):
        display=Progress(Terminal()); display.begin_upload(100)
        display.part('part',100); display.upload('part',100)
        self.assertIn('ETA verifying upload',display.line(100))
        display.verify('part')
        self.assertNotIn('verifying upload',display.line(101))

    def test_prompt_pause_suppresses_render_and_resumes(self):
        stream=Terminal(); display=Progress(stream)
        with display.pause():
            before=stream.getvalue(); display.render()
            self.assertEqual(stream.getvalue(),before)
        display.render(); self.assertIn('\r',stream.getvalue())

    def test_redirected_output_has_no_terminal_controls(self):
        stream=io.StringIO(); display=Progress(stream)
        display.render()
        self.assertNotIn('\r',stream.getvalue()); self.assertNotIn('\x1b',stream.getvalue())
        with patch.object(display.stop,'wait',return_value=True) as wait:
            display.refresh()
        wait.assert_called_once_with(5)

    def test_rclone_statistics_feed_measured_upload_progress(self):
        display=Progress(Terminal()); display.begin_upload(1000)
        display.part('part-00000',100)
        class Process:
            stderr=io.StringIO(json.dumps({'stats':{'bytes':75}})+'\n')
            returncode=0
            def wait(self, **kwargs): return 0
            def poll(self): return 0
        with patch.object(package_publish.subprocess,'Popen',return_value=Process()) as spawn:
            package_publish.copy_part(['rclone','copyto','source','remote'],display,'part-00000')
        self.assertEqual(display.done,75)
        self.assertIn('100ms',spawn.call_args.args[0])
