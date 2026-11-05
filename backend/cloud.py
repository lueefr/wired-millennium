"""Lumen-compatible CloudRedirect configuration, staged OAuth and native stats sync.

File/API contract follows swwayps/lumen lua/cloudsettings.lua. No payload or
account tokens are exposed to the frontend. Provider semantics come from the
same CloudRedirect CLI used by Lumen.
"""
from localization import t
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from moon import steam_root
from steam_paths import vdf

CONFIG=Path.home()/'.config/CloudRedirect/config.json'
CLI=Path.home()/'.local/share/CloudRedirect/cloud_redirect_cli'
HOOK=Path.home()/'.local/share/CloudRedirect/cloud_redirect.so'
LOCK=threading.RLock()
STAGED={}
PENDING=None
PROVIDERS=('local','folder','gdrive','onedrive','r2','s3')
OAUTH={
    'gdrive':dict(client_id='1072944905499-vm2v2i5dvn0a0d2o4ca36i1vge8cvbn0.apps.googleusercontent.com',client_secret='v6V3fKV_zWU7iw1DrpO1rknX',scope='https://www.googleapis.com/auth/drive.file',auth_url='https://accounts.google.com/o/oauth2/v2/auth',token_url='https://oauth2.googleapis.com/token',port=0,path='/callback'),
    'onedrive':dict(client_id='b15665d9-eda6-4092-8539-0eec376afd59',client_secret='qtyfaBBYA403=unZUP40~_#',scope='Files.ReadWrite offline_access',auth_url='https://login.microsoftonline.com/common/oauth2/v2.0/authorize',token_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',port=53682,path='/')}
META={'cn.cloudredirect','cn.dat','root_token.cloudredirect','root_token.dat','file_tokens.cloudredirect','file_tokens.dat','manifest.cloudredirect','manifest.dat','state.cloudredirect','deleted.cloudredirect','deleted.dat'}


def read(path):
    if not path.exists():return {}
    value=json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError("Invalid CloudRedirect configuration")
    return value


def config():return {'provider':'local',**read(CONFIG)}


def atomic(path,body):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.wired-cloud-',delete=False) as stream:
        temp=Path(stream.name)
        try:stream.write(body);stream.flush();os.fsync(stream.fileno())
        except BaseException:temp.unlink(missing_ok=True);raise
    try:temp.replace(path)
    finally:temp.unlink(missing_ok=True)


def write(path,value):atomic(path,json.dumps(value,ensure_ascii=False).encode())


def token_path(provider,cfg=None):
    cfg=config() if cfg is None else cfg
    name=cfg.get('token_paths',{}).get(provider)
    if not name and cfg.get('provider')==provider:name=cfg.get('token_path')
    if isinstance(name,str) and name and not any(c in name for c in ('\0','\n','\r')):
        path=Path(name)
        if not path.is_absolute():path=CONFIG.parent/path
        if '..' not in path.parts and path.resolve().is_relative_to(CONFIG.parent.resolve()):return path
    return CONFIG.parent/({'r2':'r2_credentials.json','s3':'s3_credentials.json'}.get(provider,'tokens_'+provider+'.json'))


def credentials_valid(provider,value):
    fields=('account_id','access_key_id','secret_access_key','bucket') if provider=='r2' else ('access_key_id','secret_access_key','bucket','endpoint','region')
    return all(isinstance(value.get(key),str) and value[key].strip() for key in fields)


def status():
    with LOCK:
        cfg=config();providers={}
        for provider in PROVIDERS:
            if provider=='local':entry={'authenticated':False}
            elif provider=='folder':
                folder=cfg.get('sync_folder_path','');entry={'authenticated':bool(folder) and Path(folder).is_dir(),'settings':{'sync_folder_path':folder}}
            else:
                value=read(token_path(provider,cfg))
                if provider in OAUTH:entry={'authenticated':bool(value.get('refresh_token')),'pending':provider in STAGED}
                else:
                    fields=('account_id','access_key_id','bucket','key_prefix','endpoint') if provider=='r2' else ('access_key_id','bucket','endpoint','region','key_prefix','sign_payload','allow_insecure_http','allow_insecure_tls','ca_cert_path')
                    entry={'authenticated':credentials_valid(provider,value),'settings':{key:value[key] for key in fields if key in value}}
                    entry['settings']['has_secret']=bool(value.get('secret_access_key'))
            providers[provider]=entry
        return {'installed':HOOK.is_file(),'provider':cfg['provider'],'authenticated':providers.get(cfg['provider'],{}).get('authenticated',False),'sync_achievements':cfg.get('sync_achievements') is True,'sync_playtime':cfg.get('sync_playtime') is True,'sync_activity':cfg.get('stats_sync_enabled') is not False and cfg.get('sync_achievements') is True and cfg.get('sync_playtime') is True,'providers':providers}


def clean_env():
    env=os.environ.copy()
    for key in ('LD_PRELOAD','LD_AUDIT','LD_LIBRARY_PATH','STEAM_RUNTIME_LIBRARY_PATH','STEAM_ZENITY'):env.pop(key,None)
    return env


def cli(command,args=(),timeout=90):
    if not CLI.is_file():raise RuntimeError("CloudRedirect CLI not installed")
    result=subprocess.run([str(CLI),command,*map(str,args)],env=clean_env(),stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=timeout)
    records=[]
    for line in result.stdout.splitlines():
        try:value=json.loads(line)
        except ValueError:continue
        if isinstance(value,dict):records.append(value)
    if command=='migrate':
        last=next((item for item in reversed(records) if item.get('type')=='complete'),None)
        if result.returncode or not last or last.get('failed')!=0:raise RuntimeError("Migration not completed; the previous configuration will be preserved")
        return last
    last=records[-1] if records else {}
    if result.returncode or last.get('success') is not True:raise RuntimeError("CloudRedirect provider did not complete the operation")
    return last


def oauth_credentials(provider,cfg):
    value={**OAUTH[provider]}
    for key in ('client_id','client_secret'):
        if cfg.get(provider+'_'+key):value[key]=cfg[provider+'_'+key]
    return value


def oauth_exchange(provider,code,redirect,verifier,cfg):
    p=oauth_credentials(provider,cfg)
    body={'code':code,'client_id':p['client_id'],'client_secret':p['client_secret'],'redirect_uri':redirect,'grant_type':'authorization_code','code_verifier':verifier}
    if provider=='onedrive':body['scope']=p['scope']
    req=urllib.request.Request(p['token_url'],data=urllib.parse.urlencode(body).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req,timeout=20) as response:token=json.load(response)
    except Exception:raise RuntimeError("Unable to complete login to provider") from None
    if not isinstance(token,dict) or not token.get('refresh_token'):raise RuntimeError("The provider did not provide a renewal token")
    return {'access_token':token.get('access_token',''),'refresh_token':token['refresh_token'],'expires_at':time.time()+float(token.get('expires_in',3600))}


def cancel_auth():
    global PENDING
    with LOCK:
        if PENDING:PENDING['cancel'].set();PENDING['server'].server_close()
        PENDING=None


def authorize(provider):
    global PENDING
    if provider not in OAUTH:raise ValueError("This provider does not use OAuth sign-in")
    with LOCK:
        cancel_auth();cfg=config();p=oauth_credentials(provider,cfg)
        verifier=secrets.token_urlsafe(64);state=secrets.token_urlsafe(32)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        pending={'provider':provider,'status':'waiting','cancel':threading.Event(),'deadline':time.monotonic()+300}
        class Callback(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                parsed=urllib.parse.urlsplit(self.path);query=urllib.parse.parse_qs(parsed.query)
                if parsed.path!=p['path']:self.send_error(404);return
                if not secrets.compare_digest(query.get('state',[''])[0],state):self.send_error(400);return
                code=query.get('code',[''])[0]
                if not code or len(code)>8192:
                    pending.update(status='error',error="Login canceled or refused by provider");self.send_error(400);return
                with LOCK:
                    if PENDING is not pending or pending['cancel'].is_set():self.send_error(410);return
                    pending['status']='authenticating'
                success=False
                try:
                    value=oauth_exchange(provider,code,redirect,verifier,cfg)
                    with LOCK:
                        if PENDING is pending and not pending['cancel'].is_set():
                            final=token_path(provider,cfg);staged=final.with_name(final.name+'.wired-pending');write(staged,value);STAGED[provider]=staged
                            pending['status']='done';success=True
                except Exception:
                    with LOCK:
                        if PENDING is pending:pending.update(status='error',error="Unable to complete login to provider")
                body=t("Login completed. Go back to Steam and click Save and Restart." if success else "Login not completed. Return to Steam and try again.").encode()
                self.send_response(200 if success else 400);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:self.wfile.write(body)
                except OSError:pass
        class LocalServer(HTTPServer):
            allow_reuse_address=True
            def get_request(self):
                client,address=super().get_request();client.settimeout(2);return client,address
        try:server=LocalServer(('127.0.0.1',p['port']),Callback)
        except OSError:raise RuntimeError("Provider login port is busy") from None
        server.timeout=.25
        redirect='http://localhost:'+str(server.server_port)+p['path']
        query={'client_id':p['client_id'],'redirect_uri':redirect,'response_type':'code','scope':p['scope'],'prompt':'consent','state':state,'code_challenge':challenge,'code_challenge_method':'S256'}
        if provider=='gdrive':query['access_type']='offline'
        pending['server']=server;PENDING=pending
        def listen():
            try:
                while not pending['cancel'].is_set() and pending['status']=='waiting' and time.monotonic()<pending['deadline']:server.handle_request()
                with LOCK:
                    if PENDING is pending and pending['status']=='waiting' and not pending['cancel'].is_set():pending.update(status='timeout',error='Sign-in expired')
            except (ValueError,OSError):pass
            finally:server.server_close()
        threading.Thread(target=listen,daemon=True,name='wired-cloud-login').start()
        return {'auth_url':p['auth_url']+'?'+urllib.parse.urlencode(query),'status':'waiting'}


def auth_poll():
    with LOCK:return {key:PENDING[key] for key in ('provider','status','error') if key in PENDING} if PENDING else {'status':'idle'}


def discard():
    cancel_auth()
    with LOCK:
        for path in STAGED.values():path.unlink(missing_ok=True)
        STAGED.clear()
    return {'success':True}


def schedule_restart():
    helper=Path(__file__).with_name('restart_steam.sh')
    env=clean_env()
    result=subprocess.run(['/bin/bash',str(helper),'--check'],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
    if result.returncode:raise RuntimeError("Injected launcher not available; Steam has not been closed")
    subprocess.Popen(['/bin/bash',str(helper)],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    return True


def apply(request,restart=schedule_restart):
    """Promote credentials and all toggles together; rollback on probe/restart failure."""
    provider=request.get('provider')
    if provider not in PROVIDERS or type(request.get('sync_activity')) is not bool:raise ValueError("Invalid cloud configuration")
    with LOCK:
        cfg=config();source=cfg.get('provider','local');snapshots={CONFIG:CONFIG.read_bytes() if CONFIG.exists() else None}
        def snapshot(path):
            if path not in snapshots:snapshots[path]=path.read_bytes() if path.exists() else None
        try:
            if provider in OAUTH:
                final=token_path(provider,cfg);snapshot(final)
                if provider in STAGED:write(final,read(STAGED[provider]))
                if not read(final).get('refresh_token'):raise ValueError("Login to provider before saving")
            elif provider in ('r2','s3'):
                final=token_path(provider,cfg);snapshot(final)
                credentials={**request.get('credentials',{})}
                if not credentials.get('secret_access_key'):credentials['secret_access_key']=read(final).get('secret_access_key')
                if not credentials_valid(provider,credentials):raise ValueError("Fill in provider credentials")
                write(final,credentials)
            elif provider=='folder':
                folder=request.get('sync_folder_path','')
                if not isinstance(folder,str) or not Path(folder).is_absolute() or any(c in folder for c in ('\0','\n','\r')):raise ValueError("Choose a folder with absolute path")
                Path(folder).mkdir(parents=True,exist_ok=True);cfg['sync_folder_path']=folder
            sign_out=request.get('sign_out_provider')
            if sign_out in ('gdrive','onedrive','r2','s3') and sign_out!=provider:
                old=token_path(sign_out,cfg);snapshot(old);old.unlink(missing_ok=True)
            if provider not in ('local','folder'):
                cfg.setdefault('token_paths',{})[provider]=str(token_path(provider,cfg))
            if request.get('migrate') is True and source!=provider and source not in ('local','folder'):
                cfg.setdefault('token_paths',{})[source]=str(token_path(source,config()))
            cfg.update(provider=provider,stats_sync_enabled=request['sync_activity'],sync_achievements=request['sync_activity'],sync_playtime=request['sync_activity'])
            write(CONFIG,cfg)
            if provider in ('r2','s3'):cli('list-remote-app-ids',[provider,0])
            if request.get('migrate') is True and source!=provider and source!='local' and provider!='local':cli('migrate',[source,provider],timeout=1800)
            if restart() is not True:raise RuntimeError("Unable to restart Steam")
        except Exception:
            for path,body in reversed(list(snapshots.items())):
                if body is None:path.unlink(missing_ok=True)
                else:atomic(path,body)
            raise
        discard()
        return {'success':True,'restarting':True}


def local_apps():
    storage=CONFIG.parent/'storage';apps=[];accounts={}
    try:
        users=vdf((steam_root()/'config/loginusers.vdf').read_text()).get('users',{})
        for sid,info in users.items():
            if sid.isdigit() and isinstance(info,dict):accounts[int(sid)-76561197960265728]={'name':info.get('personaname',''),'files':0,'size':0}
    except (OSError,ValueError,RuntimeError):pass
    if storage.is_dir():
        for account in storage.iterdir():
            if not account.name.isdecimal() or account.is_symlink() or not account.is_dir():continue
            number=int(account.name);summary=accounts.setdefault(number,{'name':'','files':0,'size':0})
            for app in account.iterdir():
                if not app.name.isdecimal() or app.name=='0' or app.is_symlink() or not app.is_dir():continue
                files=size=0
                for directory,dirs,names in os.walk(app,followlinks=False):
                    relative=Path(directory).relative_to(app)
                    dirs[:]=[name for name in dirs if not (Path(directory)/name).is_symlink()] if len(relative.parts)<32 else []
                    for name in names:
                        path=Path(directory)/name
                        if path.is_symlink() or not path.is_file():continue
                        if directory==str(app) and (name in META or __import__('re').fullmatch(r'manifest\.\d+\.cloudredirect',name)):continue
                        files+=1;size+=path.stat().st_size
                apps.append({'appid':int(app.name),'account':number,'files':files,'size':size,'local':True,'remote':False})
                summary['files']+=files;summary['size']+=size
    return {'accounts':[{'id':key,**value} for key,value in sorted(accounts.items(),key=lambda item:(-item[1]['size'],-item[1]['files'],item[0]))], 'apps':sorted(apps,key=lambda item:(item['appid'],item['account']))}


def remote_apps(account):
    account=int(account)
    if not 0<=account<2**32:raise ValueError("Invalid Steam Account")
    cfg=config();provider=cfg.get('provider','local')
    if provider=='local':return {'provider':provider,'appids':[]}
    if provider=='folder':
        root=Path(cfg.get('sync_folder_path',''))/str(account)
        return {'provider':provider,'appids':sorted(int(path.name) for path in root.iterdir() if path.is_dir() and not path.is_symlink() and path.name.isdecimal() and int(path.name)>0) if root.is_dir() else []}
    result=cli('list-remote-app-ids',[provider,account])
    return {'provider':provider,'appids':sorted(int(value) for value in result.get('app_ids',[]) if str(value).isdigit() and int(value)>0)}
