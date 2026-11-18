"""Offline coverage for the official CloudRedirect x64 dependency adapter."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT/'tools'))
import cloudredirect_dependency as cloud


def binary(bits):
    data=bytearray(20)
    data[:4]=b'\x7fELF'
    data[4]=2 if bits==64 else 1
    data[18:20]=(62 if bits==64 else 3).to_bytes(2,'little')
    return bytes(data)


class CloudDependencyTests(unittest.TestCase):
    def info(self):
        return {'repository':cloud.REPOSITORY,'version':'v2.6.5','commit':'a'*40,
                'assets':{name:{'url':'https://example.test/'+name,'sha256':'f'*64}
                          for name in cloud.BINARIES}}

    def test_resolves_only_official_sha256_assets(self):
        assets=[{'name':name,'id':n,'updated_at':'now','digest':'sha256:'+'a'*64,
                 'browser_download_url':'https://example.test/'+name}
                for n,name in enumerate(cloud.BINARIES,1)]
        def api(path):
            if path.endswith('/releases/latest'):
                return {'tag_name':'v2.6.5','assets':assets,
                        'html_url':'https://github.com/crghofficial/cloudredirect/releases/tag/v2.6.5','body':'Fixes'}
            return {'sha':'b'*40}
        with patch.object(cloud,'api',side_effect=api):
            result=cloud.resolve()
        self.assertEqual(result['repository'],'crghofficial/cloudredirect')
        self.assertEqual(result['commit'],'b'*40)
        self.assertEqual(result['assets']['cloud_redirect.so']['sha256'],'a'*64)

    def test_installs_verified_elf64_release_without_compilation(self):
        info=self.info()
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            def fetch(url,path,digest=None):
                path.write_bytes(b'upstream license' if path.name=='LICENSE' else binary(64))
            with patch.object(cloud,'fetch',side_effect=fetch),patch.object(cloud,'build') as build:
                result=cloud.prepare(info,directory)
            build.assert_not_called()
            self.assertEqual(result['method'],'official-release')
            self.assertEqual(cloud.arch(directory/'cloud_redirect.so'),64)

    def test_rebuilds_pinned_source_when_upstream_ships_elf32(self):
        info=self.info()
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            def fetch(url,path,digest=None):
                path.write_bytes(binary(32))
            def build(info,path):
                (path/'source').mkdir();(path/'build').mkdir()
                license_file=path/'source/LICENSE'
                license_file.write_text('official license')
                for name in cloud.BINARIES:(path/name).write_bytes(binary(64))
                return license_file
            with patch.object(cloud,'fetch',side_effect=fetch),patch.object(cloud,'build',side_effect=build) as compile:
                result=cloud.prepare(info,directory)
            compile.assert_called_once()
            self.assertEqual(result['method'],'official-source-x64')
            self.assertEqual((directory/'LICENSE').read_text(),'official license')
            self.assertFalse((directory/'source').exists())
            cloud.verify(directory)

    def test_rejects_invalid_header_instead_of_building_untrusted_asset(self):
        info=self.info()
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            def fetch(url,path,digest=None):path.write_bytes(b'not an ELF')
            with patch.object(cloud,'fetch',side_effect=fetch),patch.object(cloud,'build') as build:
                with self.assertRaisesRegex(ValueError,'Invalid'):cloud.prepare(info,directory)
            build.assert_not_called()

    def test_install_keeps_backup_and_receipt(self):
        info=self.info()
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);stage=base/'stage';stage.mkdir()
            home=base/'home';destination=home/'.local/share/CloudRedirect';destination.mkdir(parents=True)
            for name in cloud.FILES:(stage/name).write_bytes(b'official license' if name=='LICENSE' else binary(64))
            (destination/'cloud_redirect.so').write_bytes(b'previous')
            with patch.object(cloud.Path,'home',return_value=home),patch.object(cloud,'ROOT',base):
                receipt=cloud.install(info,stage)
            self.assertEqual(receipt['version'],info['version'])
            self.assertEqual((destination/'cloud_redirect.so.wired-backup').read_bytes(),b'previous')
            self.assertEqual((destination/'cloud_redirect.so').read_bytes(),binary(64))
            self.assertEqual((base/'cloudredirect.json').is_file(),True)


if __name__=='__main__':
    unittest.main()
