import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('moonlight_settings', ROOT/'src/client/moonlight_settings.py')
settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings)


class MoonlightSettingsTests(unittest.TestCase):
    def test_import_preserves_qt_bytes_backup_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'native.conf'; destination=Path(tmp)/'flatpak/Moonlight.conf'
            data=b'[General]\ncertificate=@ByteArray(fixture\\ncert)\nkey=fixture-key\nuniqueid=abc\n[hosts]\n1\\uuid=wolf\nsize=1\n'
            old=b'[General]\ncertificate=old\nkey=old\nuniqueid=old\n'
            source.write_bytes(data);destination.parent.mkdir();destination.write_bytes(old)
            self.assertTrue(settings.migrate(source,destination))
            self.assertEqual(destination.read_bytes(),data)
            backup=destination.with_name('Moonlight.conf.before-vastgame')
            self.assertEqual(backup.read_bytes(),old)
            self.assertEqual(destination.stat().st_mode & 0o777,0o600)
            self.assertEqual(backup.stat().st_mode & 0o777,0o600)
            self.assertFalse(settings.migrate(source,destination))
            self.assertEqual(backup.read_bytes(),old)

    def test_incomplete_native_identity_keeps_flatpak_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'native.conf';destination=Path(tmp)/'Moonlight.conf'
            source.write_text('[General]\ncertificate=fixture\n')
            destination.write_bytes(b'keep')
            with self.assertRaisesRegex(ValueError,'incomplete'):
                settings.migrate(source,destination)
            self.assertEqual(destination.read_bytes(),b'keep')
