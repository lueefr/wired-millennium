"""Independent client for the provider protocols documented by LuaTools Moon."""
from localization import t
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from components import ROOT, write_json

BASE = 'https://db.lua.tools/auth/v1'
# Public Supabase anonymous client identifier, published by the upstream client.
ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3NzYwMzkzNzYsImV4cCI6MTg5MzQ1NjAwMCwicm9sZSI6ImFub24iLCJpc3MiOiJzdXBhYmFzZSJ9.f_-K38u3odjltP-g_67FVmG32Vg-_-k-lNBvIaVUVBM'
SESSION = ROOT/'lua-tools-session.json'
LOCK = threading.RLock()
PENDING = None


def post(path, body):
    request = urllib.request.Request(BASE+path, data=json.dumps(body).encode(), headers={'Content-Type':'application/json','apikey':ANON_KEY}, method='POST')
    try:
        with urllib.request.urlopen(request,timeout=8) as response:
            value=json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'lua.tools refused authentication (HTTP{error.code}); sign in again') from None
    except (OSError,ValueError):
        raise RuntimeError("Unable to authenticate to lua.tools; try again") from None
    if not isinstance(value,dict):raise RuntimeError("Invalid response from lua.tools")
    return value


def load():
    if not SESSION.exists():return None
    value=json.loads(SESSION.read_text())
    return value if isinstance(value,dict) and value.get('refresh_token') else None


def save(value, previous=None):
    value={**value}
    if previous:
        value.setdefault('refresh_token',previous['refresh_token'])
        value.setdefault('user',previous.get('user',{}))
    if not all(isinstance(value.get(key),str) and value[key] for key in ('access_token','refresh_token')):
        raise RuntimeError("lua.tools did not return a valid session")
    value['expires_at']=time.time()+float(value.get('expires_in',3600))
    write_json(SESSION,value)
    return value


def status():
    with LOCK:
        session=load()
        meta=(session or {}).get('user',{}).get('user_metadata',{})
        name=meta.get('custom_claims',{}).get('global_name') or meta.get('full_name') or meta.get('name') or 'lua.tools'
        result={'configured':bool(session),'account':str(name) if session else '', 'status':'connected' if session else 'disconnected'}
        if PENDING:
            result.update(status=PENDING['status'],error=PENDING.get('error',''))
        return result


def access_token():
    with LOCK:
        session=load()
        if not session:return None
        if session.get('expires_at',0)<=time.time()+120:
            session=save(post('/token?grant_type=refresh_token',{'refresh_token':session['refresh_token']}),session)
        return session['access_token']


def cancel():
    global PENDING
    with LOCK:
        if PENDING:
            PENDING['cancel'].set()
            PENDING['server'].server_close()
        PENDING=None
    return {'success':True}


def logout():
    cancel()
    with LOCK:SESSION.unlink(missing_ok=True)
    return {'success':True}


def begin_login():
    global PENDING
    with LOCK:
        if PENDING and PENDING['status']=='waiting':
            return {'success':True,'auth_url':PENDING['auth_url']}
        cancel()
        verifier=secrets.token_urlsafe(64)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        pending={'status':'waiting','cancel':threading.Event(),'deadline':time.monotonic()+300}
        class Callback(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                url=urllib.parse.urlsplit(self.path)
                if url.path!='/callback':
                    self.send_error(404);return
                query=urllib.parse.parse_qs(url.query)
                code=query.get('code',[''])[0]
                if not code or len(code)>8192:
                    self.send_error(400);return
                with LOCK:
                    if PENDING is not pending or pending['cancel'].is_set():
                        self.send_error(410);return
                    pending['status']='authenticating'
                success=False
                try:
                    value=post('/token?grant_type=pkce',{'auth_code':code,'code_verifier':verifier})
                    with LOCK:
                        if PENDING is pending and not pending['cancel'].is_set():
                            save(value);pending['status']='connected';success=True
                except Exception:
                    with LOCK:
                        if PENDING is pending:pending.update(status='error',error="Unable to complete login; try again.")
                body=t("Login completed. Return to Steam." if success else "Login not completed. Return to Steam and try again.").encode()
                self.send_response(200 if success else 400);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:self.wfile.write(body)
                except OSError:pass
        class LocalServer(HTTPServer):
            allow_reuse_address=True
            def get_request(self):
                client,address=super().get_request();client.settimeout(2);return client,address
        try:server=LocalServer(('127.0.0.1',53789),Callback)
        except OSError:raise RuntimeError("lua.tools login port is busy; close another login and try again") from None
        server.timeout=.25
        auth_url=BASE+'/authorize?'+urllib.parse.urlencode({'provider':'discord','redirect_to':'http://localhost:53789/callback','code_challenge':challenge,'code_challenge_method':'s256'})
        pending['server']=server
        pending['auth_url']=auth_url
        PENDING=pending
        def listen():
            try:
                while not pending['cancel'].is_set() and pending['status']=='waiting' and time.monotonic()<pending['deadline']:
                    server.handle_request()
                with LOCK:
                    if PENDING is pending and pending['status']=='waiting' and not pending['cancel'].is_set():pending.update(status='timeout',error='Sign-in expired. Try again.')
            except (OSError,ValueError):pass
            finally:server.server_close()
        threading.Thread(target=listen,daemon=True,name='wired-lua-login').start()
        return {'success':True,'auth_url':auth_url}


def candidates(config):
    result=[]
    options=config.get('providers',{})
    if options.get('lua_tools',True):
        result.append({'name':'Luie (lua.tools)','url':'https://lua.tools/api/manifest/download?appid=<appid>&source=Luie','lua_tools':True})
    if options.get('sushi',True):
        result.append({'name':'Sushi','url':'https://raw.githubusercontent.com/sushi-dev55-alt/sushitools-games-repo-alt/refs/heads/main/<appid>.zip'})
    if options.get('ryuu',False):
        result.append({'name':'Ryuu','url':'http://167.235.229.108/<appid>','plain_http':True})
    return result


def fetch_manifest(url, headers, plain_http=False):
    if plain_http:
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='http' or parsed.netloc!='167.235.229.108' or not parsed.path.strip('/').isdigit() or headers:
            raise ValueError("Invalid Ryuu Request")
        return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'wired-millennium'}),timeout=30)
    from components import request
    return request(url,headers)
