"""lua.tools fix catalogue and reversible ZIP overlays; never executes payloads."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import urllib.parse
import zipfile

from archive_utils import validate_archive
from components import ROOT, request, write_json
from moon import app_id
from providers import access_token
from steam_paths import installed_game


def catalogue(appid):
    appid=app_id(appid)
    with request('https://lua.tools/api/denuvo/fixes?appid='+appid) as response:
        payload=json.loads(response.read(2*1024*1024))
    if not isinstance(payload,dict) or not isinstance(payload.get('fixes',[]),list):raise ValueError("Invalid patch catalog")
    entries=[]
    for fix in payload.get('fixes',[]):
        if not isinstance(fix,dict) or not re.fullmatch(r'[a-fA-F0-9-]{36}',str(fix.get('id',''))):continue
        text=(str(fix.get('title',''))+' '+json.dumps(fix.get('tags',[]))).lower()
        entries.append({'id':fix['id'],'title':str(fix.get('title',"Correction")),'description':str(fix.get('description','')),'hasFix':fix.get('hasFix') is True,'hasManifest':fix.get('hasManifest') is True,'requiresPreparation':'denuvowo' in text or 'hypervisor' in text})
    return {'appid':appid,'name':str(payload.get('name','App '+appid)),'fixes':entries}


def resolve(fix_id,slot):
    if slot not in ('manifest','fix') or not re.fullmatch(r'[a-fA-F0-9-]{36}',str(fix_id)):raise ValueError("Invalid fix")
    token=access_token()
    if not token:raise RuntimeError("Enter lua.tools in Wired settings")
    url='https://lua.tools/api/denuvo/download?'+urllib.parse.urlencode({'fix':fix_id,'slot':slot})
    with request(url,{'Authorization':'Bearer '+token}) as response:result=json.loads(response.read(1024*1024))
    signed=result.get('url','')
    parsed=urllib.parse.urlsplit(signed)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or any(c in signed for c in ('\r','\n')):raise ValueError("Invalid fix link")
    return signed


def fetch(url,destination,job,manager):
    size=0
    with request(url) as response,destination.open('wb') as output:
        total=int(response.headers.get('Content-Length',0))
        if total>512*1024*1024:raise ValueError("Fix larger than 512 MiB")
        while chunk:=response.read(65536):
            if job['_cancel'].is_set():raise InterruptedError("Canceled")
            size+=len(chunk)
            if size>512*1024*1024:raise ValueError("Fix larger than 512 MiB")
            output.write(chunk);manager.update(job['id'],bytes=size,total=total,message="Downloading lua.tools fix")


def safe_target(game,relative):
    target=game/relative
    for node in (target,*target.parents):
        if node==game:break
        if node.is_symlink():raise ValueError("Patch target contains symlink")
    if not target.resolve().is_relative_to(game):raise ValueError("Fix outside of game folder")
    return target


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_closed(appid):
    marker=('SteamAppId='+str(appid)).encode()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():continue
        try:
            if marker in (proc/'environ').read_bytes().split(b'\0'):
                raise RuntimeError("Close the game before applying or restoring a fix")
        except (OSError,PermissionError):continue


def apply(job,manager):
    args=job['_args'];appid=app_id(args['appid']);identity=args['fix_id']
    selected=next((fix for fix in catalogue(appid)['fixes'] if fix['id']==identity),None)
    if not selected or not selected['hasFix']:raise ValueError("Fix contains no applicable files")
    if selected['requiresPreparation']:raise RuntimeError("This fix requires hypervisor preparation, not yet integrated into Wired")
    game=installed_game(appid);ensure_closed(appid)
    ledger=ROOT/'fixes'/appid/'receipt.json'
    if ledger.exists():raise RuntimeError("Restore the previous fix before applying another")
    ledger.parent.mkdir(parents=True,exist_ok=True)
    backup=ledger.parent/'originals'
    with tempfile.TemporaryDirectory(prefix='fix-',dir=ROOT) as temp:
        archive=Path(temp)/'fix.zip';fetch(resolve(identity,'fix'),archive,job,manager)
        if not zipfile.is_zipfile(archive):raise ValueError("Only ZIP fixes can be applied internally; this package uses another format")
        validate_archive(archive)
        files=[]
        with zipfile.ZipFile(archive) as bundle:
            entries=[item for item in bundle.infolist() if not item.is_dir()]
            if not entries:raise ValueError("Empty fix")
            # Validate every destination and stage every original before publishing.
            for item in entries:
                target=safe_target(game,item.filename)
                if target.exists() and not target.is_file():raise ValueError("Destination is not a file")
                original=backup/item.filename
                if target.exists():original.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,original)
                files.append({'path':item.filename,'original':target.exists(),'sha256':hashlib.sha256(bundle.read(item)).hexdigest()})
            record={'appid':appid,'fix_id':identity,'title':selected['title'],'game':str(game),'files':files,'state':'applying'}
            write_json(ledger,record)
            written=[]
            try:
                for item in entries:
                    if job['_cancel'].is_set():raise InterruptedError("Canceled")
                    target=safe_target(game,item.filename);target.parent.mkdir(parents=True,exist_ok=True)
                    staged=Path(temp)/'next';staged.write_bytes(bundle.read(item));staged.chmod(target.stat().st_mode&0o777 if target.exists() else 0o644)
                    # Copy to the game's filesystem before atomic replacement.
                    with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.wired-fix-',delete=False) as stream:
                        temporary=Path(stream.name)
                    try:shutil.copy2(staged,temporary);temporary.replace(target)
                    finally:temporary.unlink(missing_ok=True)
                    written.append(item.filename)
                write_json(ledger,{**record,'state':'applied'})
            except Exception:
                for item in reversed(files):
                    if item['path'] not in written:continue
                    target=safe_target(game,item['path'])
                    if item['original']:shutil.copy2(backup/item['path'],target)
                    else:target.unlink(missing_ok=True)
                ledger.unlink(missing_ok=True)
                raise
    return {'appid':appid,'title':selected['title'],'files':len(files),'message':"Fix applied. Previous files have been preserved for restoration."}


def restore(appid):
    appid=app_id(appid);game=installed_game(appid);ensure_closed(appid)
    ledger=ROOT/'fixes'/appid/'receipt.json'
    if not ledger.exists():raise ValueError("No fixes managed for this game")
    record=json.loads(ledger.read_text())
    if record['game']!=str(game):raise ValueError('The game library changed; backups were preserved')
    if record.get('state')!='applied':raise ValueError("There is an application stopped; backups were preserved")
    for item in record['files']:
        target=safe_target(game,item['path'])
        if not target.is_file() or digest(target)!=item['sha256']:raise ValueError("Files changed after fix; automatic restore stopped to preserve them")
    for item in record['files']:
        target=safe_target(game,item['path'])
        if item['original']:shutil.copy2(ledger.parent/'originals'/item['path'],target)
        else:target.unlink()
    ledger.unlink()
    return {'appid':appid,'message':"Previous files restored."}


def import_manifest(job,manager):
    from moon import import_package
    args=job['_args'];appid=app_id(args['appid']);identity=args['fix_id']
    fix=next((entry for entry in catalogue(appid)['fixes'] if entry['id']==identity),None)
    if not fix or not fix['hasManifest']:raise ValueError("Manifest not available for this game")
    with tempfile.TemporaryDirectory(prefix='fix-manifest-',dir=ROOT) as temp:
        path=Path(temp)/'manifest';fetch(resolve(identity,'manifest'),path,job,manager)
        if zipfile.is_zipfile(path):return import_package(path,appid)
        text=path.read_text(encoding='utf-8-sig')
        archive=Path(temp)/'manifest.zip'
        with zipfile.ZipFile(archive,'w') as bundle:bundle.writestr(appid+'.lua',text)
        return import_package(archive,appid)
