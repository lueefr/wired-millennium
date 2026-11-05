import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
sys.modules.setdefault('Millennium', types.SimpleNamespace())
import components
from archive_utils import validate_archive
import jobs
import main
from jobs import JobManager


def wait_for(predicate, timeout=5):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(.01)
    raise AssertionError("Timeout waiting for task")


class BackendTests(unittest.TestCase):
    def test_zip_rejects_traversal_and_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root/'unsafe.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('../outside', 'bad')
            with self.assertRaises(ValueError):
                components.extract_zip(archive, root/'out')
            with self.assertRaises(ValueError):
                validate_archive(archive)
            with zipfile.ZipFile(archive, 'w') as bundle:
                info = zipfile.ZipInfo('link'); info.external_attr = 0o120777 << 16
                bundle.writestr(info, '/etc/passwd')
            with self.assertRaises(ValueError):
                validate_archive(archive)

    def test_checksum_mismatch_removes_download(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'artifact'
            with patch.object(components, 'request', return_value=io.BytesIO(b'wrong')):
                with self.assertRaises(RuntimeError):
                    components.fetch('https://example.test', path, '0'*64)
            self.assertFalse(path.exists())

    def test_provider_redirect_does_not_leak_authorization(self):
        import urllib.request
        opener=types.SimpleNamespace(open=lambda *args,**kwargs:io.BytesIO(b'ok'))
        with patch.object(components.urllib.request,'build_opener',return_value=opener) as factory:
            components.request('https://lua.tools/test',{'Authorization':'Bearer test-secret'})
            handler=factory.call_args.args[0]
        request=urllib.request.Request('https://lua.tools/test',headers={'Authorization':'Bearer test-secret'})
        forwarded=handler.redirect_request(request,None,302,'Found',{},'https://storage.example/file')
        self.assertIsNone(forwarded.get_header('Authorization'))
        same=handler.redirect_request(request,None,302,'Found',{},'https://lua.tools/another')
        self.assertEqual(same.get_header('Authorization'),'Bearer test-secret')
        with self.assertRaises(ValueError):handler.redirect_request(request,None,302,'Found',{},'http://storage.example/file')

    def test_failed_prepare_keeps_previous_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            components.write_json(root/'prepared.json', {'previous': True})
            with patch.object(components, 'ROOT', root), patch.object(components, 'latest', return_value={'accela': {'url': 'https://example.test', 'asset': 'deps.tar.gz'}}), patch.object(components, 'fetch', side_effect=OSError('network')):
                with self.assertRaises(OSError):
                    components.prepare()
            self.assertEqual(json.loads((root/'prepared.json').read_text()), {'previous': True})

    def test_active_steam_blocks_install(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(components, 'ROOT', Path(temp)), patch.object(components.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(RuntimeError, 'Close Steam'):
                components.install()

    def test_settings_migrate_gui_path_and_validate(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(main, 'CONFIG', Path(temp)/'settings.json'):
            config = {'api_list': [{'url': 'https://example.test/<appid>', 'enabled': True}], 'accela_location': '/old/run.sh'}
            main.SaveSettings(json.dumps(config))
            value = json.loads(main.GetSettings())
            self.assertNotIn('accela_location', value)
            self.assertIn('accela_settings', value)
            self.assertEqual(main.CONFIG.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                main.SaveSettings(json.dumps({'api_list': [{'url': 'http://example.test/<appid>'}]}))
            with self.assertRaises(ValueError):
                main.SaveSettings(json.dumps({'api_list': [], 'accela_settings': {'max_downloads': 0}}))

    def test_queue_deduplicates_reorders_and_cancels(self):
        started = threading.Event(); release = threading.Event(); order = []
        def execute(manager, job):
            order.append(job['action'])
            if len(order) == 1:
                started.set(); release.wait(3)
            return {'ok': True}
        with patch.object(JobManager, 'execute', execute):
            manager = JobManager(lambda: {})
            try:
                first = manager.enqueue('health'); started.wait(1)
                same = manager.enqueue('health')
                self.assertEqual(first['job_id'], same['job_id'])
                second = manager.enqueue('library')
                third = manager.enqueue('sls_status')
                fourth = manager.enqueue('check_updates')
                manager.cancel(fourth['job_id'])
                manager.move(third['job_id'], 'up')
                release.set()
                wait_for(lambda: manager.jobs[second['job_id']]['status'] == 'done')
                self.assertEqual(order, ['health', 'sls_status', 'library'])
                self.assertEqual(manager.jobs[fourth['job_id']]['status'], 'cancelled')
            finally:
                release.set(); manager.close(); manager.thread.join(2)

    def test_api_fallback_gets_valid_zip(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w') as archive:
            archive.writestr('123.lua', 'addappid(123)')
        class Response(io.BytesIO):
            headers = {}
        manager = JobManager(lambda: {})
        try:
            job = {'id': 'test', '_args': {'appid': 123}, '_cancel': threading.Event(), 'logs': []}
            manager.jobs['test'] = job
            config = {'providers': {'lua_tools':False,'sushi':False}, 'api_list': [{'url': 'https://one.test/<appid>'}, {'url': 'https://two.test/<appid>'}]}
            with tempfile.TemporaryDirectory() as temp, patch.object(jobs, 'request', side_effect=[Response(b'invalid'), Response(content.getvalue())]):
                archive = manager._archive(job, config, Path(temp))
                self.assertTrue(zipfile.is_zipfile(archive))
                self.assertEqual(sum(v['level']=='warning' for v in job['logs']), 1)
        finally:
            manager.close(); manager.thread.join(2)

    def test_hubcap_key_used_for_native_manifest_import(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w') as archive:
            archive.writestr('123.lua', 'addappid(123)')
        class Response(io.BytesIO):
            headers = {}
        manager = JobManager(lambda: {})
        try:
            job = {'id': 'hubcap', '_args': {'appid': 123}, '_cancel': threading.Event(), 'logs': []}
            manager.jobs['hubcap'] = job
            with tempfile.TemporaryDirectory() as temp, patch.object(jobs, 'request', return_value=Response(content.getvalue())) as request:
                archive = manager._archive(job, {'api_list': [], 'accela_settings': {'morrenus_api_key': ' test-key '}}, Path(temp))
                self.assertTrue(zipfile.is_zipfile(archive))
                request.assert_called_once_with('https://hubcapmanifest.com/api/v1/manifest/123', {'Authorization': 'Bearer test-key'})
                self.assertNotIn('test-key', json.dumps(manager.snapshot()))
        finally:
            manager.close(); manager.thread.join(2)

    def test_automatic_provider_fallback_skips_errors_and_wrong_app(self):
        import providers
        def package(appid):
            content=io.BytesIO()
            with zipfile.ZipFile(content,'w') as archive:archive.writestr(str(appid)+'.lua','addappid('+str(appid)+')')
            return content.getvalue()
        class Response(io.BytesIO):headers={}
        manager=JobManager(lambda:{})
        try:
            job={'id':'fallback','_args':{'appid':123},'_cancel':threading.Event(),'logs':[]};manager.jobs['fallback']=job
            config={'api_list':[],'accela_settings':{'morrenus_api_key':'test-hubcap'}}
            with tempfile.TemporaryDirectory() as temporary,patch.object(providers,'access_token',return_value='test-lua'),patch.object(jobs,'request',side_effect=[OSError('unavailable'),Response(package(456)),Response(package(123))]) as request:
                manager._archive(job,config,Path(temporary))
                urls=[call.args[0] for call in request.call_args_list]
                self.assertIn('hubcapmanifest.com',urls[0]);self.assertIn('lua.tools',urls[1]);self.assertIn('sushi',urls[2])
                self.assertEqual(request.call_args_list[2].args[1],{})
                self.assertEqual(sum(v['level']=='warning' for v in job['logs']),2)
                self.assertNotIn('test-lua',json.dumps(manager.snapshot()))
        finally:manager.close();manager.thread.join(2)

    def test_plain_lua_provider_response(self):
        class Response(io.BytesIO):
            headers={'Content-Type':'text/plain'}
            status=200
        manager=JobManager(lambda:{})
        try:
            job={'id':'lua','_args':{'appid':123},'_cancel':threading.Event(),'logs':[]};manager.jobs['lua']=job
            config={'providers':{'lua_tools':False,'sushi':False},'api_list':[{'name':'Lua source','url':'https://test.invalid/<appid>'}]}
            with tempfile.TemporaryDirectory() as temporary,patch.object(jobs,'request',return_value=Response(b'addappid(123)')):
                path=manager._archive(job,config,Path(temporary))
                with zipfile.ZipFile(path) as archive:self.assertEqual(archive.read('123.lua'),b'addappid(123)')
                self.assertTrue(any('HTTP=200' in v['message'] for v in job['logs']))
        finally:manager.close();manager.thread.join(2)

    def test_two_managers_serialize_workers(self):
        entered = threading.Event(); release = threading.Event(); order = []
        def execute(manager, job):
            order.append(job['action'])
            if job['action'] == 'health':
                entered.set(); release.wait(3)
            return {'ok': True}
        with tempfile.TemporaryDirectory() as temp, patch.object(jobs, 'ROOT', Path(temp)), patch.object(JobManager, '_execute', execute):
            first = JobManager(lambda: {}); second = JobManager(lambda: {})
            try:
                first.enqueue('health'); self.assertTrue(entered.wait(1))
                identity = second.enqueue('library')['job_id']
                wait_for(lambda: second.jobs[identity]['message'].startswith('Waiting'))
                self.assertEqual(order, ['health'])
                release.set()
                wait_for(lambda: second.jobs[identity]['status'] == 'done')
                self.assertEqual(order, ['health', 'library'])
            finally:
                release.set(); first.close(); second.close()
                first.thread.join(2); second.thread.join(2)

    def test_prompt_validates_job_and_choices(self):
        manager = JobManager(lambda: {})
        try:
            fake = types.SimpleNamespace(stdin=io.StringIO())
            manager.current = 'job'
            manager.process = fake
            manager.jobs['job'] = {'status': 'waiting', 'prompt': {'id': 'p', 'kind': 'depots', 'choices': [{'value': '124'}], 'multiple': True}}
            with self.assertRaises(ValueError):
                manager.reply('job', 'stale', ['124'])
            with self.assertRaises(ValueError):
                manager.reply('job', 'p', ['999'])
            manager.reply('job', 'p', ['124'])
            self.assertEqual(json.loads(fake.stdin.getvalue())['answer'], ['124'])
            self.assertIsNone(manager.jobs['job']['prompt'])
        finally:
            manager.current = None; manager.close(); manager.thread.join(2)

    def test_cancel_terminates_paused_process_group(self):
        # Real worker process, without Steam or native components.
        manager = JobManager(lambda: {})
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            with manager.lock:
                manager.current = 'job'; manager.process = process
                manager.jobs['job'] = {'status': 'working', 'action': 'health', 'prompt': None, '_cancel': threading.Event()}
            self.assertTrue(manager.pause(True)['success'])
            manager.cancel('job')
            process.wait(timeout=4)
            self.assertEqual(manager.jobs['job']['status'], 'cancelling')
        finally:
            if process.poll() is None:
                jobs.JobManager._signal(process, signal.SIGKILL); process.wait()
            manager.current = None; manager.close(); manager.thread.join(2)

    def test_latest_selects_assets_and_pins_cloud_commit(self):
        def fake(path):
            if path.endswith('/releases/latest'):
                name = 'deps.tar.gz' if path.startswith('ciscosweater') else 'slsteam-moon-linux-v1.zip'
                return {'tag_name': 'v1', 'assets': [{'name': name, 'browser_download_url': 'https://example.test/'+name, 'updated_at': 'now'}]}
            if '/commits/' in path:
                return {'sha': 'abc123'}
            return {'default_branch': 'main'}
        with patch.object(components, 'api', side_effect=fake):
            result = components.latest()
        self.assertEqual(result['cloudredirect']['version'], 'abc123')
        self.assertEqual(result['accela']['commit'], 'abc123')


if __name__ == '__main__':
    unittest.main()
