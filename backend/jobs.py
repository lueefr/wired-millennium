"""Sequential jobs, selection IPC and process-group control for the internal engine."""
from collections import deque
import json
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile

from diagnostics import emit, redact
from components import ROOT, request
from runtime import ensure_runtime, runtime_env
from archive_utils import validate_archive, validate_manifest_package

ACTIONS = {'health', 'download', 'inspect', 'library', 'check_updates', 'search', 'api_status', 'dependencies', 'chmod', 'goldberg_apply', 'goldberg_remove', 'steamless', 'achievements', 'shortcuts', 'sls_status', 'sls_token', 'sls_fake', 'sls_fake_remove', 'sls_repair', 'uninstall', 'prepare', 'manifest_import', 'integration_remove', 'cloud_update', 'cloud_status', 'fixes_catalog', 'fix_apply', 'fix_restore', 'fix_manifest', 'cloud_apply', 'cloud_apps', 'cloud_remote'}
TERMINAL = {'done', 'error', 'cancelled'}


class JobManager:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.jobs = {}
        self.queue = deque()
        self.current = None
        self.process = None
        self.closed = False
        self.thread = threading.Thread(target=self._work, daemon=True, name='wired-jobs')
        self.thread.start()

    def enqueue(self, action, args=None):
        if action not in ACTIONS:
            raise ValueError("Unknown operation")
        args = dict(args or {})
        with self.condition:
            if self.closed:
                raise RuntimeError("Plugin is closing")
            if len(self.queue) >= 50:
                raise RuntimeError("Queue full")
            for job in self.jobs.values():
                if job['status'] not in TERMINAL and job['action'] == action and job['_args'] == args:
                    return {'success': True, 'job_id': job['id'], 'existing': True}
            identity = uuid.uuid4().hex
            self.jobs[identity] = {'id': identity, 'action': action, 'appid': args.get('appid'), 'name': args.get('name', ''), 'phase': 'pending', 'status': 'queued', 'message': "In the queue", 'percent': None, 'bytes': 0, 'total': 0, 'speed': None, 'bytes_estimated': False, 'logs': [], 'prompt': None, 'result': None, '_args': args, '_cancel': threading.Event()}
            self.queue.append(identity)
            self.condition.notify()
            return {'success': True, 'job_id': identity}

    @staticmethod
    def public(job):
        return {key: value for key, value in job.items() if not key.startswith('_')}

    def snapshot(self):
        with self.lock:
            current = self.jobs.get(self.current)
            return {'current': self.public(current) if current else None, 'jobs': [self.public(j) for j in list(self.jobs.values())[-50:]], 'queue': list(self.queue)}

    def update(self, identity, **values):
        with self.lock:
            job = self.jobs[identity]
            if 'bytes' in values:
                now = time.monotonic()
                previous = job.get('_sample')
                if previous and values['bytes'] >= previous[1] and now > previous[0]:
                    values['speed'] = (values['bytes']-previous[1])/(now-previous[0])
                job['_sample'] = (now, values['bytes'])
            job.update(values)

    def log(self, identity, message, level='info'):
        with self.lock:
            logs = self.jobs[identity]['logs']
            message = redact(message)
            job = self.jobs[identity]
            emit(f"job={identity} action={job.get('action', 'unknown')} appid={job.get('appid')}: {message}", level)
            logs.append({'message': message, 'level': level})
            del logs[:-80]

    def cancel(self, identity=None):
        with self.lock:
            identity = identity or self.current
            if identity not in self.jobs:
                return {'success': False, 'error': "Operation not found"}
            job = self.jobs[identity]
            if job['status'] in TERMINAL:
                return {'success': True}
            if job['action'] == 'prepare' and job['status'] != 'queued':
                return {'success': False, 'error': "Ongoing preparation needs to end"}
            job['_cancel'].set()
            job['prompt'] = None
            if job['status'] == 'queued':
                job.update(status='cancelled', message="Removed from queue")
            else:
                job.update(status='cancelling', message="Canceling; partial files will be kept")
                process = self.process
                if process and process.poll() is None:
                    self._signal(process, signal.SIGCONT)
                    self._signal(process, signal.SIGTERM)
                    threading.Thread(target=self._reap_cancel, args=(process,), daemon=True).start()
            return {'success': True}

    @staticmethod
    def _signal(process, signum):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    def _reap_cancel(self, process):
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        # The worker may exit while a grandchild still ignores SIGTERM.
        self._signal(process, signal.SIGKILL)

    def pause(self, paused):
        with self.lock:
            job = self.jobs.get(self.current)
            if not job or not self.process or self.process.poll() is not None or job['prompt'] or job['status'] not in ('working', 'paused'):
                return {'success': False, 'error': "No worker running to pause/resume"}
            self._signal(self.process, signal.SIGSTOP if paused else signal.SIGCONT)
            job['status'] = 'paused' if paused else 'working'
            job['speed'] = None
            job.pop('_sample', None)
            return {'success': True}

    def reply(self, identity, prompt_id, answer, cancel=False):
        with self.lock:
            job = self.jobs.get(identity)
            current_prompt = job.get('prompt') if job else None
            if identity != self.current or not current_prompt or current_prompt['id'] != prompt_id or not self.process:
                raise ValueError("Outdated selection")
            if not cancel:
                choices = {str(c['value']) for c in current_prompt.get('choices', [])}
                if current_prompt.get('multiple'):
                    if not isinstance(answer, list) or not set(answer).issubset(choices):
                        raise ValueError("Invalid selection")
                elif choices and answer not in choices:
                    raise ValueError("Invalid option")
                elif current_prompt['kind'] == 'confirm' and type(answer) is not bool:
                    raise ValueError("Invalid confirmation")
            response = {'id': prompt_id, 'answer': answer, 'cancel': bool(cancel)}
            self.process.stdin.write(json.dumps(response)+'\n')
            self.process.stdin.flush()
            job.update(prompt=None, status='working')
            return {'success': True}

    def move(self, identity, direction):
        with self.lock:
            pending = list(self.queue)
            if identity not in pending or self.jobs[identity]['status'] != 'queued':
                raise ValueError("Only queued tasks can be moved")
            index = pending.index(identity)
            target = max(0, min(len(pending)-1, index+(-1 if direction == 'up' else 1)))
            pending[index], pending[target] = pending[target], pending[index]
            self.queue = deque(pending)
            return {'success': True}

    def close(self):
        with self.lock:
            self.closed = True
            if self.current:
                self.cancel(self.current)
            for identity in self.queue:
                self.jobs[identity]['_cancel'].set()
                self.jobs[identity]['status'] = 'cancelled'
            self.condition.notify_all()

    def _work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.queue or self.closed)
                if self.closed:
                    return
                identity = self.queue.popleft()
                job = self.jobs[identity]
                if job['_cancel'].is_set():
                    continue
                self.current = identity
                job.update(status='working', message='Starting')
            self.log(identity, "Task started")
            try:
                result = self.execute(job)
                self.log(identity, "Task canceled" if job['_cancel'].is_set() else "Task completed")
                self.update(identity, status='cancelled' if job['_cancel'].is_set() else 'done', result=result, prompt=None)
            except Exception as exc:
                self.log(identity, type(exc).__name__+': '+str(exc), 'error')
                self.update(identity, status='cancelled' if job['_cancel'].is_set() else 'error', message=str(exc), prompt=None)
            finally:
                with self.lock:
                    self.process = None
                    self.current = None
                    # Keep history bounded, without dropping queued/running jobs.
                    finished = [k for k, j in self.jobs.items() if j['status'] in TERMINAL]
                    for key in finished[:-40]:
                        del self.jobs[key]

    def _archive(self, job, config, directory, publish=None):
        args = job['_args']
        archive = directory/'package.zip'
        if args.get('zip_path'):
            path = Path(args['zip_path']).expanduser()
            if not path.is_file() or path.stat().st_size > 256*1024*1024:
                raise ValueError('Local ZIP is missing or larger than 256 MiB')
            import shutil
            shutil.copyfile(path, archive)
            validate_archive(archive)
            if job['_cancel'].is_set():
                raise InterruptedError("Canceled")
            return publish(archive) if publish else archive
        appid = str(int(args['appid']))
        endpoints = []
        custom = [item for item in config.get('api_list', []) if item.get('enabled', True)]
        hubcap_key = config.get('accela_settings', {}).get('morrenus_api_key', '').strip()
        if hubcap_key and config.get('providers',{}).get('hubcap',True):
            endpoints.append({'name': 'Hubcap', 'url': 'https://hubcapmanifest.com/api/v1/manifest/<appid>', 'api_key': hubcap_key})
        from providers import candidates
        endpoints.extend(candidates(config))
        endpoints.extend(custom)
        if not endpoints:
            raise RuntimeError("Login to lua.tools or paste your Hubcap key into Wired settings on Millennium or import a local ZIP")
        self.log(job['id'], 'Provider order: '+', '.join(str(e.get('name','API')) for e in endpoints))
        conflicts = []
        for attempt, endpoint in enumerate(endpoints, 1):
            started = time.monotonic()
            self.log(job['id'], f"Attempt {attempt}/{len(endpoints)}: {endpoint.get('name', 'API')}")
            if job['_cancel'].is_set():
                raise InterruptedError("Canceled")
            self.update(job['id'], message="Consulting "+str(endpoint.get('name', 'API')), bytes=0, total=0)
            headers = {'Authorization': 'Bearer '+endpoint['api_key']} if endpoint.get('api_key') else {}
            try:
                if endpoint.get('lua_tools'):
                    from providers import access_token
                    token=access_token()
                    if not token:
                        self.log(job['id'], "lua.tools: missing session; trying next provider", 'warning')
                        continue
                    headers={'Authorization':'Bearer '+token}
                from providers import fetch_manifest
                url = endpoint['url'].replace('<appid>', appid)
                response = fetch_manifest(url, headers, True) if endpoint.get('plain_http') else request(url, headers)
                with response, archive.open('wb') as output:
                    total = int(response.headers.get('Content-Length', 0))
                    self.log(job['id'], f"HTTP={getattr(response, 'status', 'unknown')} content_type={response.headers.get('Content-Type', 'unknown')} declared_size={total}")
                    if total > 256*1024*1024:
                        raise ValueError("Package larger than 256 MiB")
                    size = 0
                    while chunk := response.read(65536):
                        if job['_cancel'].is_set():
                            raise InterruptedError("Canceled")
                        size += len(chunk)
                        if size > 256*1024*1024:
                            raise ValueError("Package larger than 256 MiB")
                        output.write(chunk)
                        self.update(job['id'], bytes=size, total=total)
                self.log(job['id'], f'Received {size} bytes in {time.monotonic()-started:.2f}s')
                if not zipfile.is_zipfile(archive):
                    import re
                    try:
                        text=archive.read_text(encoding='utf-8-sig') if archive.stat().st_size<=16*1024*1024 else ''
                    except UnicodeDecodeError:
                        raise ValueError("Binary response not recognized as ZIP") from None
                    match=re.search(r'(?mi)^\s*addappid\s*\(\s*(\d+)',text)
                    if not match or int(match[1])!=int(appid):
                        raise ValueError("Response does not contain ZIP or Lua script of the requested AppID")
                    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
                        bundle.writestr(appid+'.lua',text)
                    self.log(job['id'], "Lua response converted to internal package; script not executed")
                validate_manifest_package(archive,appid)
                self.log(job['id'], str(endpoint.get('name','API'))+": package validated for AppID "+appid)
            except InterruptedError:
                raise
            except Exception as exc:
                self.log(job['id'], str(endpoint.get('name',"Provider"))+': '+type(exc).__name__+': '+str(exc)+f'; duration={time.monotonic()-started:.2f}s; trying next', 'warning')
                continue
            if job['_cancel'].is_set():
                raise InterruptedError("Canceled")
            if publish:
                from moon import ManifestConflictError
                try:
                    return publish(archive)
                except ManifestConflictError as exc:
                    conflicts.append(str(exc))
                    self.log(job['id'], str(endpoint.get('name','Provider'))+': '+str(exc)+f'; duration={time.monotonic()-started:.2f}s; trying next', 'warning')
                    continue
            return archive
        if conflicts:
            raise RuntimeError("No provider could import a package without conflicting with existing manifests: "+'; '.join(dict.fromkeys(conflicts)))
        raise RuntimeError("Providers did not return a valid package. Check the lua.tools login or Hubcap key in Wired settings.")

    def execute(self, job):
        ROOT.mkdir(parents=True, exist_ok=True)
        with (ROOT/'worker.lock').open('w') as lock:
            while True:
                if job['_cancel'].is_set():
                    raise InterruptedError("Canceled")
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self.update(job['id'], message='Waiting for another engine process')
                    job['_cancel'].wait(.1)
            return self._execute(job)

    def _execute(self, job):
        identity = job['id']
        if job['action'] in ('cloud_apply','cloud_apps','cloud_remote'):
            import cloud
            if job['action']=='cloud_apps':return cloud.local_apps()
            if job['action']=='cloud_remote':return cloud.remote_apps(job['_args']['account'])
            return cloud.apply(job['_args'])
        if job['action'] in ('fixes_catalog','fix_apply','fix_restore','fix_manifest'):
            from fixes import catalogue, apply, restore, import_manifest
            if job['action']=='fixes_catalog':return catalogue(job['_args']['appid'])
            if job['action']=='fix_restore':return restore(job['_args']['appid'])
            if job['action']=='fix_manifest':return import_manifest(job,self)
            return apply(job,self)
        if job['action'] == 'prepare':
            from components import prepare
            result = prepare(lambda message: self.update(identity, message=message))
            info = ensure_runtime(lambda message: self.update(identity, message=message))
            return {'components': result, 'engine_version': info['version']}
        if job['action'] in ('manifest_import', 'integration_remove', 'cloud_update', 'cloud_status'):
            from moon import import_package, remove_integration, cloud_status
            if job['action'] == 'integration_remove':
                return remove_integration(job['_args']['appid'])
            if job['action'] == 'cloud_status':
                return cloud_status(job['_args'].get('provider','folder'))
            if job['action'] == 'cloud_update':
                from components import update_cloud
                return update_cloud(lambda message:self.update(identity,message=message))
            with tempfile.TemporaryDirectory(prefix='manifest-',dir=ROOT) as temporary:
                return self._archive(job,self.settings(),Path(temporary),publish=lambda archive: import_package(archive,job['_args']['appid']))
        info = ensure_runtime(lambda message: self.update(identity, message=message))
        config = self.settings()
        ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='job-', dir=ROOT) as directory:
            directory = Path(directory)
            args = dict(job['_args'])
            if job['action'] in ('inspect', 'download') and (args.get('zip_path') or args.get('appid') or config.get('api_list')):
                args['zip_path'] = str(self._archive(job, config, directory))
            if job['_cancel'].is_set():
                raise InterruptedError("Canceled")
            env = runtime_env()
            env['TMPDIR'] = str(directory)
            payload = {'source': info['source'], 'state_dir': str(ROOT/'engine-data'), 'settings': config.get('accela_settings', {}), 'action': job['action'], 'args': args}
            # stderr is kept separate from the JSON protocol, never inserted into HTML.
            with tempfile.TemporaryFile(mode='w+') as errors:
                with self.lock:
                    if job['_cancel'].is_set():
                        raise InterruptedError("Canceled")
                    process = subprocess.Popen([info['python'], '-u', str(Path(__file__).with_name('engine_worker.py'))], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, encoding='utf-8', env=env, start_new_session=True)
                    self.process = process
                    process.stdin.write(json.dumps(payload)+'\n')
                    process.stdin.flush()
                result = None
                received_result = False
                error = None
                try:
                    for line in process.stdout:
                        try:
                            value = json.loads(line)
                        except ValueError:
                            continue
                        kind = value.get('event')
                        if kind == 'progress':
                            updates = {k: v for k, v in value.items() if k in ('percent', 'message', 'bytes', 'total', 'phase', 'bytes_estimated')}
                            self.update(identity, **updates)
                        elif kind == 'metadata':
                            self.update(identity,appid=value.get('appid'),name=value.get('name',''))
                        elif kind == 'log':
                            self.log(identity, value.get('message', ''), value.get('level', 'info'))
                        elif kind == 'prompt':
                            if not job['_cancel'].is_set():
                                self.update(identity, prompt=value, status='waiting', message=value.get('title', "Selection required"))
                        elif kind == 'result':
                            result, received_result = value.get('value'), True
                        elif kind in ('error', 'cancelled'):
                            error = value.get('message', "Internal engine failure")
                    code = process.wait()
                finally:
                    if process.poll() is None:
                        self._signal(process, signal.SIGCONT)
                        self._signal(process, signal.SIGKILL)
                        process.wait()
                    process.stdin.close()
                    process.stdout.close()
                if job['_cancel'].is_set():
                    raise InterruptedError("Canceled")
                if code or error or not received_result:
                    raise RuntimeError(error or f'Internal engine terminated without result (code{code})')
                self.update(identity, message="Operation completed", percent=100)
                return result
