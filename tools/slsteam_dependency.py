"""Installer-only dependency. Never shipped to or invoked by the plugin backend."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from components import ROOT, api, fetch, extract_zip, write_json

REPOSITORY = 'swwayps/slsteam-moon'


def resolve():
    release = api(REPOSITORY+'/releases/latest')
    assets = release['assets']
    candidates = [a for a in assets if a['name'].endswith('.zip') and 'linux' in a['name'].lower()]
    if len(candidates) != 1:
        raise RuntimeError("Release slsteam-moon without an unambiguous Linux package")
    asset = candidates[0]
    checksum = next((a for a in assets if a['name'] == asset['name']+'.sha256'), None)
    if not checksum:
        raise RuntimeError("slsteam-moon release did not publish checksum")
    from components import request
    with request(checksum['browser_download_url']) as response:
        expected = response.read(16384).decode().split()[0].lower()
    return {'repository': REPOSITORY, 'version': release['tag_name'], 'url': asset['browser_download_url'], 'asset': asset['name'], 'sha256': expected}


def install():
    info = resolve()
    binary = Path.home()/'.local/share/SLSsteam/SLSsteam.so'
    receipt = ROOT/'dependencies/slsteam-moon.json'
    if receipt.exists() and binary.is_file():
        old = json.loads(receipt.read_text())
        if old.get('version') == info['version'] and old.get('binary_sha256') == hashlib.sha256(binary.read_bytes()).hexdigest():
            print("slsteam-moon dependency already installed:", info['version'])
            return info
    for name in ('steam', 'steamwebhelper'):
        if subprocess.run(['pgrep','-x',name],stdout=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError("Close Steam before installing/updating slsteam-moon")
    ROOT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='slsteam-installer-',dir=ROOT) as temp:
        temp = Path(temp)
        archive = temp/info['asset']
        # Reuse a previously downloaded, verified release if available.
        reused = False
        previous = ROOT/'prepared.json'
        if previous.exists():
            old = json.loads(previous.read_text())
            candidate = Path(old['directory'])/'slssteam'/info['asset']
            if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == info['sha256']:
                shutil.copy2(candidate,archive); reused=True
        if not reused:
            fetch(info['url'],archive,info['sha256'])
        extract_zip(archive,temp/'release')
        setups = list((temp/'release').glob('*/setup.sh'))
        if len(setups) != 1:
            raise RuntimeError("Incompatible slsteam-moon installer layout")
        env = os.environ.copy()
        for key in ('LD_AUDIT','LD_PRELOAD','LD_LIBRARY_PATH','STEAM_RUNTIME_LIBRARY_PATH'):
            env.pop(key,None)
        # User launchers cover native Steam without modifying system-owned launchers.
        env['SLSM_SUDO_DENIED']='1'
        wrapper = str(Path.home()/'.local/share/SLSsteam/path')
        env['PATH']=':'.join(p for p in env.get('PATH','/usr/bin:/bin').split(':') if p and p.rstrip('/') != wrapper)
        subprocess.run(['bash',str(setups[0]),'install'],cwd=setups[0].parent,env=env,check=True,stdin=subprocess.DEVNULL)
        if not binary.is_file():
            raise RuntimeError('The installer finished without SLSsteam.so')
        config = Path.home()/'.config/SLSsteam/config.yaml'
        defaults = setups[0].parent/'res/config.yaml'
        if not config.exists() and defaults.exists():
            config.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(defaults,config)
    write_json(receipt,{**info,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()})
    return info
