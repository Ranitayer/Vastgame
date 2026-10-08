"""Import boundary checks; no cloud account or VM required."""
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/client'))
import game_catalog
import ingest
import package_publish

PE = b'MZ'+bytes(58)+(64).to_bytes(4, 'little')+b'PE\0\0'


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root/'download.zip'

    def zip(self, entries):
        with zipfile.ZipFile(self.archive, 'w') as output:
            for name, data in entries: output.writestr(name, data)
        return self.archive

    @unittest.skipUnless(hasattr(zipfile, 'ZIP_ZSTANDARD'), 'Python 3.14 Zstandard ZIP support required')
    def test_zstandard_zip_validates_and_extracts_with_crc_checks(self):
        with zipfile.ZipFile(self.archive,'w',compression=zipfile.ZIP_ZSTANDARD) as output:
            output.writestr('Game/Game.exe',PE)
            output.writestr('Game/data.bin',b'game data'*100)
        records=ingest.members(self.archive,self.root)
        self.assertEqual(records[0].compress_type,93)
        folder=ingest.extract(self.archive,self.root)
        self.assertEqual((folder/'Game/Game.exe').read_bytes(),PE)
        self.assertEqual((folder/'Game/data.bin').read_bytes(),b'game data'*100)

    def test_nested_package_uses_shared_detector(self):
        self.zip([('Game/Game.exe', PE), ('Game/data.bin', b'data'), ('Game/setup.exe', PE)])
        folder = ingest.extract(self.archive, self.root)
        manifest = game_catalog.create(folder, 'fixture')
        self.assertEqual(manifest['game']['executable'], 'Game.exe')
        self.assertEqual(manifest['game']['arguments'], [])
        self.assertEqual(manifest['source']['path'], str(folder/'Game'))

    def test_ambiguous_executables_require_selection(self):
        source = self.root/'game'; source.mkdir()
        for name in ('Game.exe', 'Game-Win64-Shipping.exe'): (source/name).write_bytes(PE)
        with patch.object(sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Ambiguous'): game_catalog.detect(source)
        self.assertEqual(game_catalog.detect(source, 'Game.exe')[1], 'Game.exe')

    def test_installer_and_fake_executable_are_not_games(self):
        source = self.root/'game'; source.mkdir()
        (source/'setup.exe').write_bytes(PE); (source/'Game.exe').write_text('not an executable')
        with self.assertRaisesRegex(ValueError, 'No portable'): game_catalog.detect(source)

    def test_unsafe_zip_paths_and_collisions(self):
        for entries in ([('../escape.exe', PE)], [('/escape.exe', PE)], [('C:/Game.exe', PE)],
                        [('a\\Game.exe', PE)], [('Game.exe', PE), ('game.exe', PE)],
                        [('folder', b'file'), ('folder/Game.exe', PE)], [('NUL.exe', PE)]):
            with self.subTest(entries=entries):
                self.zip(entries)
                with self.assertRaises(ValueError): ingest.members(self.archive, self.root)
        self.assertFalse((self.root.parent/'escape.exe').exists())

    def test_zip_symlinks_rejected(self):
        info = zipfile.ZipInfo('Game.exe'); info.create_system=3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.zip([(info, b'../../outside')])
        with self.assertRaisesRegex(ValueError, 'links'): ingest.members(self.archive, self.root)

    def test_failed_publication_keeps_staging_and_catalog_empty(self):
        cache=self.root/'cache'; catalog=self.root/'catalog'; job=cache/hashlib.sha256(b'https://example.com/game.zip').hexdigest()
        job.mkdir(parents=True)
        self.zip([('Game.exe', PE)])
        with patch.object(ingest, 'download', return_value=self.archive), patch.object(ingest, 'publish', side_effect=ValueError('remote verification failed')):
            with self.assertRaises(ValueError): ingest.ingest('https://example.com/game.zip',catalog,cache,'fixture')
        self.assertFalse(catalog.exists()); self.assertTrue((job/'extracted/Game.exe').exists())

    def test_success_publishes_catalog_without_ephemeral_source(self):
        self.zip([('Game.exe', PE)])
        def publish(manifest, source, work, imported=False, progress=None):
            result=json.loads(manifest.read_text()); result.pop('source')
            self.assertFalse((self.root/'catalog/fixture/manifest.json').exists())
            self.assertTrue(imported)
            return result
        with patch.object(ingest, 'download', return_value=self.archive), patch.object(ingest, 'publish', side_effect=publish):
            ingest.ingest('https://example.com/game.zip',self.root/'catalog',self.root/'cache','fixture')
        result=json.loads((self.root/'catalog/fixture/manifest.json').read_text())
        self.assertNotIn('source',result)
        self.assertEqual(list((self.root/'cache').iterdir()),[])

    def test_http_resume_validates_range_and_does_not_append_full_response(self):
        data=self.zip([('Game.exe',PE)]).read_bytes()
        (self.root/'download.zip').write_bytes(data[:20])
        ingest.atomic(self.root/'download.json',dict(etag='"v1"',complete=False,total=len(data)))
        class Response(io.BytesIO):
            status=206; url='https://example.com/game.zip'
            headers={'ETag':'"v1"','Content-Range':f'bytes 20-{len(data)-1}/{len(data)}'}
        def open_request(request, **kwargs):
            self.assertEqual(request.get_header('Range'), 'bytes=20-')
            return Response(data[20:])
        with patch.object(ingest.urllib.request,'urlopen',side_effect=open_request):
            self.assertEqual(ingest.download('https://example.com/game.zip',self.root).read_bytes(),data)
        ingest.atomic(self.root/'download.json',dict(etag='"v1"',complete=False,total=len(data)))
        self.archive.write_bytes(data[:20])
        Response.status=200; Response.headers={'Content-Length':str(len(data))}
        with patch.object(ingest.urllib.request,'urlopen',return_value=Response(data)):
            self.assertEqual(ingest.download('https://example.com/game.zip',self.root).read_bytes(),data)

    def test_html_and_self_extracting_exe_rejected(self):
        class Response(io.BytesIO):
            status=200; url='https://example.com/game.zip'; headers={}
        for data, headers in ((b'<html>login',{'Content-Type':'text/html'}),(PE+ b'PK\x03\x04',{})):
            Response.headers=headers
            with patch.object(ingest.urllib.request,'urlopen',return_value=Response(data)):
                with self.assertRaisesRegex(ValueError,'Unsupported ingest format'):
                    ingest.download('https://example.com/game.zip',self.root)

    def test_encrypted_and_multipart_zip_rejected_before_extraction(self):
        data=bytearray(self.zip([('Game.exe', PE)]).read_bytes())
        central=data.index(b'PK\x01\x02')
        data[central+8:central+10]=(1).to_bytes(2,'little')
        self.archive.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'Password'): ingest.members(self.archive,self.root)
        data=bytearray(self.zip([('Game.exe', PE)]).read_bytes())
        end=data.rfind(b'PK\x05\x06'); data[end+4:end+6]=(1).to_bytes(2,'little')
        self.archive.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'Multipart'): ingest.members(self.archive,self.root)

    def test_stream_writer_yields_only_bounded_chunks(self):
        class Process:
            def __init__(self, data): self.stdout=io.BytesIO(data)
            def wait(self, **kwargs): return 0
            def poll(self): return 0
        digest=hashlib.sha256()
        with patch.object(package_publish.subprocess,'Popen',side_effect=[Process(b'tar'),Process(b'123456789')]):
            sizes=[]
            for path, part, md5 in package_publish.compressed_parts(self.root,self.root,digest,chunk_bytes=4):
                sizes.append(part['size']); self.assertEqual(part['sha256'],package_publish.hash_file(path))
                path.unlink()
        self.assertEqual(sizes,[4,4,1])
        self.assertEqual(digest.hexdigest(),hashlib.sha256(b'123456789').hexdigest())

    def test_hash_objects_cannot_escape_game_namespace(self):
        from multipart_restore import package_parts
        source=self.root/'game'; source.mkdir(); (source/'Game.exe').write_bytes(PE)
        manifest=game_catalog.create(source,'fixture')
        part=dict(name='part-00000',sha256='a'*64,size=3,object='games/other/objects/'+ 'a'*64+'.part')
        manifest['package']=dict(archive='games/fixture/v1/game.tar.zst',size=3,parts=[part])
        with self.assertRaisesRegex(ValueError,'Unsafe package object'): package_parts(manifest)
