"""Regression tests for manifest import fallback after depotcache conflicts."""
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
import jobs
import moon
from jobs import JobManager


def package(*manifests):
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w') as bundle:
        bundle.writestr('123.lua', 'addappid(123)\naddappid(456)\n')
        for name, data in manifests:
            bundle.writestr(name, data)
    return content.getvalue()


class Response(io.BytesIO):
    status = 200

    def __init__(self, content):
        super().__init__(content)
        self.headers = {'Content-Length': str(len(content)), 'Content-Type': 'application/zip'}


class ManifestFallbackTests(unittest.TestCase):
    def run_import(self, root, responses, zip_path=None):
        config = {
            'providers': {'hubcap': False, 'lua_tools': False, 'sushi': False, 'ryuu': False},
            'api_list': [
                {'name': 'First', 'url': 'https://first.test/<appid>'},
                {'name': 'Second', 'url': 'https://second.test/<appid>'},
            ],
        }
        manager = JobManager(lambda: config)
        args = {'appid': 123}
        if zip_path:
            args['zip_path'] = str(zip_path)
        job = {'id': 'manifest-fallback', 'action': 'manifest_import', 'appid': 123, '_args': args,
               '_cancel': threading.Event(), 'logs': []}
        manager.jobs[job['id']] = job
        try:
            with patch.object(jobs, 'ROOT', root/'data'), patch.object(moon, 'ROOT', root/'data'), \
                 patch.object(moon, 'steam_root', return_value=root/'steam'), \
                 patch.object(jobs, 'request', side_effect=responses) as request:
                try:
                    return manager.execute(job), job['logs'], request.call_count
                except Exception as exc:
                    return exc, job['logs'], request.call_count
        finally:
            manager.close()
            manager.thread.join(2)

    def test_conflict_tries_next_provider_and_preserves_existing_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root/'steam/depotcache'
            cache.mkdir(parents=True)
            (cache/'456_789.manifest').write_bytes(b'existing')
            first = package(('456_788.manifest', b'rolled-back'), ('456_789.manifest', b'conflict'))
            second = package(('456_789.manifest', b'existing'))
            result, logs, count = self.run_import(root, [Response(first), Response(second)])
            self.assertIsInstance(result, dict)
            self.assertEqual(result['appid'], '123')
            self.assertEqual(count, 2)
            self.assertEqual((cache/'456_789.manifest').read_bytes(), b'existing')
            self.assertFalse((cache/'456_788.manifest').exists())
            self.assertTrue((root/'steam/config/stplug-in/123.lua').is_file())
            self.assertTrue((root/'data/apps/123.json').is_file())
            self.assertTrue(any('different content' in item['message'] and item['level'] == 'warning' for item in logs))
            self.assertTrue(any('Attempt 2/2: Second' in item['message'] for item in logs))

    def test_all_conflicting_providers_leave_existing_files_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root/'steam/depotcache'
            cache.mkdir(parents=True)
            (cache/'456_789.manifest').write_bytes(b'existing')
            first = package(('456_789.manifest', b'conflict-1'))
            second = package(('456_789.manifest', b'conflict-2'))
            result, logs, count = self.run_import(root, [Response(first), Response(second)])
            self.assertIsInstance(result, RuntimeError)
            self.assertIn('No provider could import a package', str(result))
            self.assertIn('456_789.manifest', str(result))
            self.assertEqual(count, 2)
            self.assertEqual((cache/'456_789.manifest').read_bytes(), b'existing')
            self.assertFalse((root/'steam/config/stplug-in/123.lua').exists())
            self.assertFalse((root/'data/apps/123.json').exists())
            self.assertEqual(sum(item['level'] == 'warning' for item in logs), 2)

    def test_unrelated_import_error_does_not_try_other_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root/'steam/config/stplug-in/123.lua'
            script.parent.mkdir(parents=True)
            script.write_text('external')
            first = package(('456_789.manifest', b'content'))
            result, _, count = self.run_import(root, [Response(first), Response(first)])
            self.assertIsInstance(result, RuntimeError)
            self.assertIn('external script', str(result))
            self.assertEqual(count, 1)
            self.assertEqual(script.read_text(), 'external')

    def test_local_zip_conflict_does_not_use_network_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root/'steam/depotcache'
            cache.mkdir(parents=True)
            (cache/'456_789.manifest').write_bytes(b'existing')
            archive = root/'local.zip'
            archive.write_bytes(package(('456_789.manifest', b'conflict')))
            result, _, count = self.run_import(root, [Response(b'unused')], zip_path=archive)
            self.assertIsInstance(result, moon.ManifestConflictError)
            self.assertEqual(count, 0)
            self.assertEqual((cache/'456_789.manifest').read_bytes(), b'existing')


if __name__ == '__main__':
    unittest.main()
