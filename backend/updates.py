"""Fixed-slot upstream monitoring and explicitly approved, staged component updates."""
from datetime import datetime, timedelta
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError

from components import ROOT, api, fetch, request, write_json
from diagnostics import emit, redact

HOURS=(1,7,13,19)
REPOSITORIES={'slssteam':'swwayps/slsteam-moon','cloudredirect':'swwayps/cloudredirect-moon'}
STOP=threading.Event()


def slot(now=None):
    """Missed slots coalesce; a late check never shifts the wall-clock schedule."""
    shifted=(now or datetime.now().astimezone())-timedelta(hours=1)
    return shifted.strftime('%Y-%m-%d')+':'+str(shifted.hour//6)


def next_check(now=None):
    now=now or datetime.now().astimezone()
    for hour in HOURS:
        candidate=now.replace(hour=hour,minute=0,second=0,microsecond=0)
        if candidate>now:return candidate.isoformat()
    return (now+timedelta(days=1)).replace(hour=1,minute=0,second=0,microsecond=0).isoformat()


def state():
    path=ROOT/'updates.json'
    return json.loads(path.read_text()) if path.exists() else {'repositories':{}}


def save(value):write_json(ROOT/'updates.json',value)


class Locked:
    def __enter__(self):
        ROOT.mkdir(parents=True,exist_ok=True)
        self.file=(ROOT/'updates.lock').open('a')
        fcntl.flock(self.file,fcntl.LOCK_EX)
        return self
    def __exit__(self,*args):self.file.close()


def optional(path):
    try:return api(path)
    except HTTPError as error:
        if error.code==404:return None
        raise


def snapshot(component):
    repository=REPOSITORIES[component]
    info=api(repository)
    branch=info['default_branch']
    tip=api(repository+'/commits/'+branch)
    result={'repository':repository,'commit':tip['sha'],'title':tip['commit']['message'].splitlines()[0],
            'url':f'https://github.com/{repository}/commit/'+tip['sha']}
    if component=='slssteam':
        release=optional(repository+'/releases/latest')
        if release:
            assets=[asset for asset in release['assets'] if asset['name'].endswith('.zip') and 'linux' in asset['name'].lower()]
            if len(assets)==1:
                asset=assets[0]
                checksum=next((a for a in release['assets'] if a['name']==asset['name']+'.sha256'),None)
                result.update(version=release['tag_name'],release_notes=release.get('body','')[:12000],release_url=release['html_url'])
                if checksum:
                    result['artifact']={'url':asset['browser_download_url'],'checksum_url':checksum['browser_download_url'],'asset':asset['name'],'version':release['tag_name']}
                    result['artifact_id']=str(asset['id'])+':'+asset.get('updated_at','')+':'+checksum.get('updated_at','')
    else:
        blobs={}
        for filename in ('cloud_redirect.so','cloud_redirect_cli','LICENSE'):
            item=optional(repository+'/contents/'+filename+'?ref='+tip['sha'])
            if item:blobs[filename]=item['sha']
        if len(blobs)==3:
            result.update(artifact={'commit':tip['sha'],'blobs':blobs},artifact_id=hashlib.sha256(json.dumps({name:blobs[name] for name in ('cloud_redirect.so','cloud_redirect_cli')},sort_keys=True).encode()).hexdigest(),version=tip['sha'][:10])
    result['revision']=hashlib.sha256(json.dumps({'commit':result['commit'],'artifact_id':result.get('artifact_id')},sort_keys=True).encode()).hexdigest()
    return result


def changelog(repository,before,after):
    if before and before!=after:
        compare=api(repository+'/compare/'+before+'...'+after)
        return [entry['commit']['message'][:1500] for entry in compare.get('commits',[])][-30:]
    return []


def installed_version(component):
    path=ROOT/('dependencies/slsteam-moon.json' if component=='slssteam' else 'cloudredirect.json')
    if path.exists():return json.loads(path.read_text()).get('version')
    return None


def check(now=None):
    # Claim one fixed slot under a process lock, then release it during networking.
    with Locked():
        value=state();current=slot(now)
        if value.get('slot')==current:return False
        value['slot']=current;value['checked_at']=(now or datetime.now().astimezone()).isoformat();save(value)
    for component,repository in REPOSITORIES.items():
        try:
            fresh=snapshot(component)
            with Locked():
                value=state();record=value['repositories'].setdefault(component,{})
                old=record.get('observed')
            changed=old is not None and (old['commit']!=fresh['commit'] or old.get('artifact_id')!=fresh.get('artifact_id'))
            known=installed_version(component)
            missing_update=old is None and known and fresh.get('artifact') and known!=fresh.get('version') and not (component=='cloudredirect' and known==fresh['artifact'].get('commit'))
            if changed or missing_update:
                notes=changelog(repository,old['commit'] if old else known if component=='cloudredirect' else None,fresh['commit'])
                if not notes:notes=[fresh.get('release_notes') or fresh['title']]
                with Locked():
                    value=state();record=value['repositories'].setdefault(component,{})
                    previous=record.get('pending',{})
                    installable=bool(fresh.get('artifact')) and (not old or fresh.get('artifact_id')!=old.get('artifact_id'))
                    # Keep an unaccepted binary update available when later commits change only source.
                    if not installable and previous.get('installable') and previous.get('decision') not in ('installed','queued'):
                        fresh['artifact']=previous['target']['artifact'];fresh['artifact_id']=previous['target']['artifact_id'];installable=True
                    record['pending']={'component':component,'revision':fresh['revision'],'repository':repository,'version':fresh.get('version',fresh['commit'][:10]),'url':fresh.get('release_url',fresh['url']),'changes':notes,'installable':installable,'decision':'available','target':fresh}
                    record['observed']=fresh;record.pop('error',None);save(value)
                emit(repository+': upstream update detected ('+fresh['commit'][:10]+')')
            else:
                with Locked():
                    value=state();record=value['repositories'].setdefault(component,{})
                    record['observed']=fresh;record.pop('error',None);save(value)
                emit(repository+': update check complete; no new revision')
        except Exception as error:
            with Locked():
                value=state();value['repositories'].setdefault(component,{})['error']=redact(error);save(value)
            emit(repository+': update check failed: '+str(error),'warning')
    return True


def status():
    with Locked():
        value=state()
        pending=[{key:item for key,item in record['pending'].items() if key!='target'} for record in value['repositories'].values() if record.get('pending')]
        return {'updates':pending,'checked_at':value.get('checked_at'),'next_check':next_check(),'hours':list(HOURS),'errors':{key:record['error'] for key,record in value['repositories'].items() if record.get('error')}}


def steam_arch():
    from moon import steam_root
    root=steam_root()
    for p in Path('/proc').iterdir():
        if not p.name.isdecimal():continue
        try:
            executable=(p/'exe').resolve()
            if executable in (root/'steamrt64/steam',root/'ubuntu12_32/steam'):return elf_arch(executable)
        except OSError:pass
    return elf_arch(root/('ubuntu12_32/steam' if (root/'.steam-disable-steamrt64-client').exists() else 'steamrt64/steam' if (root/'steamrt64/steam').exists() else 'ubuntu12_32/steam'))


def elf_arch(path):
    with Path(path).open('rb') as stream:header=stream.read(20)
    if len(header)<20 or header[:4]!=b'\x7fELF' or header[4] not in (1,2):raise ValueError('Invalid component ELF header')
    bits={1:32,2:64}[header[4]]
    if int.from_bytes(header[18:20],'little')!={32:3,64:62}[bits]:raise ValueError('Unsupported component CPU architecture')
    return bits


def verify_arch(paths):
    expected=steam_arch()
    for path in paths:
        if elf_arch(path)!=expected:raise ValueError('The update architecture does not match the Steam client')


def prepare(component,target):
    from archive_utils import validate_archive
    directory=ROOT/'component-updates'/component/target['revision']
    directory.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory.parent) as temporary:
        stage=Path(temporary);artifact=target['artifact']
        if component=='slssteam':
            with request(artifact['checksum_url']) as response:expected=response.read(16384).decode().split()[0].lower()
            if len(expected)!=64 or any(ch not in '0123456789abcdef' for ch in expected):raise ValueError('Invalid upstream checksum')
            fetch(artifact['url'],stage/'release.zip',expected);validate_archive(stage/'release.zip')
            from components import extract_zip
            extract_zip(stage/'release.zip',stage/'release')
            binaries=list((stage/'release').rglob('SLSsteam.so'))
            if len(binaries)!=1:raise ValueError('Ambiguous SLSsteam release layout')
            verify_arch(binaries+list((stage/'release').rglob('library-inject.so')))
            plan={**artifact,'repository':REPOSITORIES[component],'sha256':expected}
        else:
            for filename,blob in artifact['blobs'].items():
                fetch(f"https://raw.githubusercontent.com/{REPOSITORIES[component]}/{artifact['commit']}/{filename}",stage/filename)
                content=(stage/filename).read_bytes()
                if hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()!=blob:raise ValueError('Upstream artifact verification failed')
            verify_arch([stage/'cloud_redirect.so',stage/'cloud_redirect_cli']);plan=artifact
        plan['files']={str(path.relative_to(stage)):hashlib.sha256(path.read_bytes()).hexdigest() for path in stage.rglob('*') if path.is_file()}
        write_json(stage/'plan.json',plan)
        if directory.exists():shutil.rmtree(directory)
        stage.rename(directory)
    return directory


def respond(component,revision,decision):
    if component not in REPOSITORIES or decision not in ('later','download'):raise ValueError('Invalid update decision')
    with Locked():
        value=state();pending=value['repositories'].get(component,{}).get('pending')
        if not pending or pending['revision']!=revision:raise ValueError('This update notification is outdated')
        if decision=='later':pending['decision']='dismissed';save(value);return {'success':True}
        if not pending['installable']:raise ValueError('No new installable binary has been published')
        if pending['decision'] in ('preparing','queued','installed'):return {'success':True}
        pending['decision']='preparing';save(value)
    # A detached worker survives the Lua host closing with Steam.
    env=os.environ.copy()
    for key in ('LD_AUDIT','LD_PRELOAD','LD_LIBRARY_PATH','PYTHONPATH','PYTHONHOME'):env.pop(key,None)
    try:
        with (ROOT/'component-update-worker.log').open('a') as log:
            worker=subprocess.Popen(['/usr/bin/python3',str(Path(__file__).resolve()),'--prepare',component,'--revision',revision],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        with Locked():
            value=state();current=value['repositories'][component]['pending']
            if current['revision']==revision:current['worker_pid']=worker.pid;save(value)
    except Exception as error:
        with Locked():
            value=state();value['repositories'][component]['pending'].update(decision='error',error=redact(error));save(value)
        raise
    return {'success':True}


def prepare_and_wait(component,revision):
    try:
        with Locked():pending=state()['repositories'].get(component,{}).get('pending',{})
        if pending.get('revision')!=revision or pending.get('decision')!='preparing':return
        directory=prepare(component,pending['target'])
        with Locked():
            value=state();current=value['repositories'][component]['pending']
            if current['revision']!=revision or current['decision']!='preparing':return
            current.update(decision='queued',directory=str(directory));save(value)
        while steam_running():time.sleep(3)
        apply_pending()
    except Exception as error:
        with Locked():
            value=state();current=value['repositories'][component].get('pending',{})
            if current.get('revision')==revision:current.update(decision='error',error=redact(error));save(value)
        print('Component update failed: '+redact(error),flush=True)


def steam_running():
    return subprocess.run(['pgrep','-x','steam'],stdout=subprocess.DEVNULL).returncode==0 or subprocess.run(['pgrep','-x','steamwebhelper'],stdout=subprocess.DEVNULL).returncode==0


def apply_pending():
    if steam_running():return False
    ROOT.mkdir(parents=True,exist_ok=True)
    with (ROOT/'component-install.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return False
        for component in REPOSITORIES:
            with Locked():pending=state()['repositories'].get(component,{}).get('pending',{})
            if pending.get('decision')!='queued':continue
            try:
                directory=Path(pending['directory'])
                expected=(ROOT/'component-updates'/component/pending['revision']).resolve()
                if directory.resolve()!=expected or directory.is_symlink():raise ValueError('Invalid staged update directory')
                plan=json.loads((directory/'plan.json').read_text())
                for filename,digest in plan['files'].items():
                    path=(directory/filename).resolve()
                    if not path.is_relative_to(directory.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('The staged update was modified')
                if steam_running():return False
                if component=='slssteam':
                    verify_arch(list((directory/'release').rglob('SLSsteam.so')))
                    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
                    from slsteam_dependency import install
                    install(info=plan,archive_path=directory/'release.zip')
                else:
                    verify_arch([directory/'cloud_redirect.so',directory/'cloud_redirect_cli'])
                    destination=Path.home()/'.local/share/CloudRedirect';destination.mkdir(parents=True,exist_ok=True)
                    backups={}
                    try:
                        for filename in ('cloud_redirect.so','cloud_redirect_cli','LICENSE'):
                            target=destination/filename
                            backups[filename]=target.read_bytes() if target.exists() else None
                            if target.exists():shutil.copy2(target,target.with_suffix(target.suffix+'.wired-backup'))
                            temporary=destination/(filename+'.wired-new');shutil.copy2(directory/filename,temporary);temporary.chmod(0o644 if filename=='LICENSE' else 0o755);temporary.replace(target)
                        write_json(ROOT/'cloudredirect.json',{'version':plan['commit'],'sha256':{name:plan['files'][name] for name in backups},'restart_required':True})
                    except Exception:
                        for filename,content in backups.items():
                            if content is None:(destination/filename).unlink(missing_ok=True)
                            else:(destination/filename).write_bytes(content)
                        raise
                with Locked():
                    value=state();current=value['repositories'][component]['pending']
                    if current['revision']==pending['revision']:current.update(decision='installed');save(value)
                emit(REPOSITORIES[component]+': approved update installed')
            except Exception as error:
                with Locked():
                    value=state();value['repositories'][component]['pending'].update(decision='error',error=redact(error));save(value)
                emit(REPOSITORIES[component]+': installation failed: '+str(error),'error')
    return True


def cancel_pending():
    ROOT.mkdir(parents=True,exist_ok=True)
    with (ROOT/'component-install.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('A component update is being installed; wait before uninstalling Wired')
        with Locked():
            value=state()
            for record in value['repositories'].values():
                if record.get('pending'):record['pending']['decision']='dismissed'
            save(value)


def start():
    if os.environ.get('WIRED_TEST_OFFLINE')=='1':return
    def loop():
        while not STOP.is_set():
            try:check()
            except Exception as error:emit('Update monitor: '+str(error),'warning')
            STOP.wait(30)
    threading.Thread(target=loop,daemon=True,name='wired-update-monitor').start()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');parser.add_argument('--apply',action='store_true');parser.add_argument('--wait',action='store_true');parser.add_argument('--prepare',choices=list(REPOSITORIES));parser.add_argument('--revision');args=parser.parse_args()
    os.umask(0o077)
    if args.prepare:prepare_and_wait(args.prepare,args.revision)
    if args.check:check();apply_pending();print(json.dumps(status(),ensure_ascii=False))
    if args.apply:
        while steam_running() and args.wait:time.sleep(3)
        apply_pending()
