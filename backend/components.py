"""Managed upstream artifacts. Preparation never changes a Steam installation."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import urllib.parse
import zipfile
import uuid

ROOT = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share'))) / 'wired-millennium'
REPOS = {'accela': 'ciscosweater/enter-the-wired', 'cloudredirect': 'swwayps/cloudredirect-moon'}


def request(url, headers=None):
    if not url.startswith('https://'):
        raise ValueError("HTTPS must be used")
    class ProviderRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            if urllib.parse.urlsplit(newurl).scheme != 'https':
                raise ValueError('Non-HTTPS redirect rejected')
            forwarded = super().redirect_request(req, fp, code, msg, hdrs, newurl)
            if forwarded and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
                forwarded.remove_header('Authorization')
            return forwarded
    opener = urllib.request.build_opener(ProviderRedirect())
    return opener.open(urllib.request.Request(url, headers={'User-Agent': 'wired-millennium/0.4', **(headers or {})}), timeout=45)


def api(path):
    with request('https://api.github.com/repos/' + path) as response:
        return json.load(response)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def latest():
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        raise RuntimeError('Components require native Steam on Linux x86_64')
    result = {}
    for name in ('accela',):
        release = api(REPOS[name] + '/releases/latest')
        assets = release['assets']
        matches = [a for a in assets if a['name'] == 'deps.tar.gz']
        if len(matches) != 1:
            raise RuntimeError(f'Release {name} has no unambiguous artifact')
        asset = matches[0]
        result[name] = {'version': release['tag_name'], 'asset': asset['name'], 'url': asset['browser_download_url'], 'updated_at': asset['updated_at']}
        checksum = next((a for a in assets if a['name'] == asset['name']+'.sha256'), None)
        if checksum:
            with request(checksum['browser_download_url']) as response:
                result[name]['expected_sha256'] = response.read(16384).decode().split()[0].lower()
    for name in ('accela', 'cloudredirect'):
        repo = api(REPOS[name])
        commit = api(REPOS[name] + '/commits/' + repo['default_branch'])['sha']
        result.setdefault(name, {})['commit' if name == 'accela' else 'version'] = commit
    return result


def fetch(url, target, expected=None):
    digest = hashlib.sha256()
    with request(url) as response, target.open('wb') as output:
        while chunk := response.read(1024*1024):
            output.write(chunk)
            digest.update(chunk)
    actual = digest.hexdigest()
    if expected and actual != expected:
        target.unlink()
        raise RuntimeError("Upstream checksum does not match")
    return actual


def extract_zip(archive, target):
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = (target/member.filename).resolve()
            if not path.is_relative_to(target.resolve()) or (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe ZIP path')
        bundle.extractall(target)
        for member in bundle.infolist():
            mode = (member.external_attr >> 16) & 0o777
            if mode:
                (target/member.filename).chmod(mode)


def prepare(progress=lambda message: None):
    import fcntl
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT/'update.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        versions = latest()
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            stage = Path(temporary)
            records = {}
            for name, info in versions.items():
                progress("Downloading" + name)
                folder = stage/name
                folder.mkdir()
                files = {}
                if name == 'cloudredirect':
                    for filename in ('cloud_redirect.so', 'cloud_redirect_cli', 'LICENSE'):
                        url = f"https://raw.githubusercontent.com/{REPOS[name]}/{info['version']}/{filename}"
                        files[filename] = fetch(url, folder/filename)
                        (folder/filename).chmod(0o755 if filename != 'LICENSE' else 0o644)
                else:
                    files[info['asset']] = fetch(info['url'], folder/info['asset'], info.get('expected_sha256'))
                    if name == 'accela':
                        # ACCELA-only installer; the combo script would install another SLSsteam fork.
                        files['accela'] = fetch(f"https://raw.githubusercontent.com/{REPOS[name]}/{info['commit']}/accela", folder/'accela')
                    else:
                        extract_zip(folder/info['asset'], folder/'release')
                records[name] = {**info, 'sha256': files}
            # Publish a complete generation. Previous prepared versions stay available.
            generation = ROOT/('bundle-' + uuid.uuid4().hex)
            shutil.copytree(stage, generation)
            write_json(ROOT/'prepared.json', {'directory': str(generation), 'components': records})
        return records


def install():
    import fcntl
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT/'update.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if subprocess.run(['pgrep', '-x', 'steam'], stdout=subprocess.DEVNULL).returncode == 0 or subprocess.run(['pgrep', '-x', 'steamwebhelper'], stdout=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError("Close Steam before installing components")
        manifest = json.loads((ROOT/'prepared.json').read_text())
        bundle = Path(manifest['directory'])
        for name, info in manifest['components'].items():
            for filename, expected in info['sha256'].items():
                if hashlib.sha256((bundle/name/filename).read_bytes()).hexdigest() != expected:
                    raise RuntimeError('Prepared artifact was modified: ' + name)
        from runtime import ensure_runtime
        ensure_runtime(print)
        dest = Path.home()/'.local/share/CloudRedirect'
        dest.mkdir(parents=True, exist_ok=True)
        for filename in ('cloud_redirect.so', 'cloud_redirect_cli', 'LICENSE'):
            target = dest/filename
            if target.exists():
                shutil.copy2(target, target.with_suffix(target.suffix+'.wired-backup'))
            stage = dest/(filename+'.wired-new')
            shutil.copy2(bundle/'cloudredirect'/filename, stage)
            stage.replace(target)
        configure_cloud()
        write_json(ROOT/'installed.json', manifest)
        print("Engine and CloudRedirect prepared. slsteam-moon is installed by the plugin installer.")


def configure_cloud():
    config = Path.home()/'.config/CloudRedirect/config.json'
    if not config.exists():
        write_json(config, {'provider': 'local'})
    sls = Path.home()/'.config/SLSsteam/config.yaml'
    if sls.exists():
        import re
        before = sls.read_text()
        after = re.sub(r'(?m)^DisableCloud:[^\n]*', 'DisableCloud: no', before)
        if after == before and not re.search(r'(?m)^DisableCloud:', before):
            after += '\nDisableCloud: no\n'
        if after != before:
            shutil.copy2(sls, sls.with_suffix('.wired-cloud.bak'))
            temp = sls.with_suffix('.wired-new')
            temp.write_text(after)
            temp.replace(sls)


def update_cloud(progress=lambda message: None):
    import fcntl
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT/'cloud.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        repo = api(REPOS['cloudredirect'])
        commit = api(REPOS['cloudredirect']+'/commits/'+repo['default_branch'])['sha']
        destination = Path.home()/'.local/share/CloudRedirect'
        destination.mkdir(parents=True, exist_ok=True)
        hashes = {}
        with tempfile.TemporaryDirectory(dir=destination) as temporary:
            stage = Path(temporary)
            for filename in ('cloud_redirect.so','cloud_redirect_cli','LICENSE'):
                progress("Preparing CloudRedirect")
                hashes[filename] = fetch(f"https://raw.githubusercontent.com/{REPOS['cloudredirect']}/{commit}/{filename}",stage/filename)
                (stage/filename).chmod(0o644 if filename=='LICENSE' else 0o755)
            for filename in hashes:
                target = destination/filename
                if target.exists():
                    shutil.copy2(target,target.with_suffix(target.suffix+'.wired-backup'))
                (stage/filename).replace(target)
        configure_cloud()
        result = {'version':commit,'sha256':hashes,'restart_required':True}
        write_json(ROOT/'cloudredirect.json',result)
        return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Wired Millennium components')
    parser.add_argument('action', choices=('check', 'prepare', 'engine', 'install', 'status'))
    action = parser.parse_args().action
    if action == 'check':
        print(json.dumps(latest(), indent=2))
    elif action == 'prepare':
        print(json.dumps(prepare(print), indent=2))
    elif action == 'engine':
        from runtime import ensure_runtime
        print(json.dumps(ensure_runtime(print), indent=2))
    elif action == 'install':
        install()
    else:
        for filename in ('prepared.json', 'installed.json'):
            path = ROOT/filename
            print(filename, path.read_text() if path.exists() else "Not available")


if __name__ == '__main__':
    main()
