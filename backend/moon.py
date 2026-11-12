"""Steam/SLSsteam integration. SLSsteam is external; CloudRedirect is managed here."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

from archive_utils import validate_archive
from components import ROOT, write_json


class ManifestConflictError(RuntimeError):
    """An existing depotcache manifest has different content and must be preserved."""


def steam_root():
    for root in (Path.home()/'.steam/steam', Path.home()/'.local/share/Steam'):
        if (root/'steamapps').is_dir() and (root/'config').is_dir():
            return root.resolve()
    raise RuntimeError("Native Steam not found")


def app_id(value):
    value = str(value)
    if not value.isdecimal() or not 0 < int(value) < 2**32:
        raise ValueError("Invalid AppID")
    return str(int(value))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def status(ids=()):
    root = steam_root()
    binary = Path.home()/'.local/share/SLSsteam/SLSsteam.so'
    cloud = Path.home()/'.local/share/CloudRedirect/cloud_redirect.so'
    active = {'slssteam': False, 'cloudredirect': False}
    readable = False
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal(): continue
        try:
            if (process/'exe').resolve() != root/'ubuntu12_32/steam': continue
            maps = (process/'maps').read_text()
            readable = True
            active['slssteam'] |= 'SLSsteam.so' in maps
            active['cloudredirect'] |= 'cloud_redirect.so' in maps
        except OSError:
            continue
    if not readable:
        active = {'slssteam': None, 'cloudredirect': None}
    apps = {}
    for value in ids:
        value = app_id(value)
        path = root/'config/stplug-in'/f'{value}.lua'
        from steam_paths import installed_game
        try:installed_game(value,require_installed=True);installed=True
        except (RuntimeError,ValueError,OSError):installed=False
        apps[value] = {'added':path.is_file(),'installed':installed,'managed':(ROOT/'apps'/f'{value}.json').exists()}
    return {'steam_root':str(root),'slssteam':{'installed':binary.is_file(),'active':active['slssteam'],'managed':False},'cloudredirect':{'installed':cloud.is_file(),'active':active['cloudredirect'],'managed':True},'apps':apps}


def import_package(archive, appid):
    """Publish manifests first and the normalized Lua last (watcher commit point)."""
    appid = app_id(appid)
    root = steam_root()
    validate_archive(archive)
    with zipfile.ZipFile(archive) as bundle:
        lua_files = [item for item in bundle.infolist() if item.filename.lower().endswith('.lua')]
        chosen = [item for item in lua_files if Path(item.filename).name == appid+'.lua']
        if not chosen and len(lua_files)==1: chosen=lua_files
        if len(chosen)!=1: raise ValueError("The ZIP must contain exactly one matching Lua script for the AppID")
        text = bundle.read(chosen[0]).decode('utf-8-sig')
        entries = list(re.finditer(r'(?mi)^\s*addappid\s*\(\s*(\d+)\s*(?:,\s*\d+\s*,\s*["\']([a-fA-F0-9]{64})["\'])?\s*\)',text))
        if not entries or app_id(entries[0][1]) != appid:
            raise ValueError("Package AppID does not match requested")
        # Emit only recognized declarations; never execute Lua from a provider.
        lines=[]; depots=set()
        for item in entries:
            identity=app_id(item[1]);depots.add(identity)
            lines.append(f'addappid({identity}, 1, "{item[2].lower()}")' if item[2] else f'addappid({identity})')
        for match in re.finditer(r'(?mi)^\s*addtoken\s*\(\s*(\d+)\s*,\s*["\'](\d+)["\']\s*\)',text):
            if app_id(match[1]) in depots: lines.append(f'addtoken({match[1]}, "{match[2]}")')
        for match in re.finditer(r'(?mi)^\s*setManifestid\s*\(\s*(\d+)\s*,\s*["\'](\d+)["\'](?:\s*,\s*(\d+))?\s*\)',text):
            if app_id(match[1]) in depots:
                size=', '+match[3] if match[3] else ''
                lines.append(f'setManifestid({match[1]}, "{match[2]}"{size})')
        script=('\n'.join(lines)+'\n').encode()
        lua_path=root/'config/stplug-in'/f'{appid}.lua'
        receipt=ROOT/'apps'/f'{appid}.json'
        previous=json.loads(receipt.read_text()) if receipt.exists() else None
        if lua_path.is_symlink(): raise ValueError("Target script is a symbolic link")
        if lua_path.exists() and (not previous or previous.get('lua_sha256')!=sha(lua_path)):
            raise RuntimeError("An external script for this game already exists; it was preserved")
        manifests={}
        for item in bundle.infolist():
            name=Path(item.filename).name
            match=re.fullmatch(r'(\d+)_(\d+)\.manifest',name)
            if match and match[1] in depots:
                if name in manifests: raise ValueError('Duplicate manifest')
                manifests[name]=bundle.read(item)
    ledger={'appid':appid,'lua_sha256':hashlib.sha256(script).hexdigest(),'manifests':list(manifests)}
    cache=root/'depotcache'; cache.mkdir(parents=True,exist_ok=True)
    lua_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.wired-import-',dir=root) as temporary:
        stage=Path(temporary)
        written=[]; backups={}; published=False
        try:
            for name,content in manifests.items():
                target=cache/name
                if target.is_symlink():raise ValueError("Target Manifest is a symbolic link")
                if target.exists():
                    if target.read_bytes()==content:continue
                    # Reusing a manifest gid with different bytes must never corrupt another game.
                    raise ManifestConflictError("Existing Manifest has different content:"+name)
                temp=stage/name;temp.write_bytes(content);temp.chmod(0o600);temp.replace(target);written.append(target)
            if lua_path.exists():backups[lua_path]=lua_path.read_bytes()
            temp=stage/(appid+'.lua');temp.write_bytes(script);temp.chmod(0o600);temp.replace(lua_path);published=True
            write_json(receipt,ledger)
        except Exception:
            for target in written:target.unlink(missing_ok=True)
            if lua_path in backups:lua_path.write_bytes(backups[lua_path])
            elif published:lua_path.unlink(missing_ok=True)
            raise
    return {'appid':appid,'added':True,'managed':True,'manifests':len(manifests),'native_install':True,'message':"Available for installation via Steam; SLSsteam watches the script automatically."}


def remove_integration(appid):
    appid=app_id(appid)
    root=steam_root();path=root/'config/stplug-in'/f'{appid}.lua';receipt=ROOT/'apps'/f'{appid}.json'
    if not receipt.exists():raise ValueError("Script is not managed by Wired")
    saved=json.loads(receipt.read_text())
    if path.is_symlink() or path.exists() and sha(path)!=saved['lua_sha256']:
        raise ValueError('The script was changed externally and has been preserved')
    path.unlink(missing_ok=True);receipt.unlink()
    return {'appid':appid,'added':False,'game_files_preserved':True,'saves_preserved':True}


def cloud_status(provider='folder'):
    if provider not in ('folder','gdrive','onedrive','r2','s3'):raise ValueError("Invalid provider")
    cli=Path.home()/'.local/share/CloudRedirect/cloud_redirect_cli'
    if not cli.is_file():raise RuntimeError("CloudRedirect is not installed")
    env=os.environ.copy()
    for key in ('LD_LIBRARY_PATH','LD_PRELOAD','LD_AUDIT'):env.pop(key,None)
    result=subprocess.run([str(cli),'auth-status',provider],env=env,capture_output=True,text=True,timeout=20,stdin=subprocess.DEVNULL)
    try:value=json.loads(result.stdout)
    except ValueError:raise RuntimeError("CloudRedirect did not return a valid state")
    if result.returncode:raise RuntimeError(value.get('error',"CloudRedirect failure"))
    return value
