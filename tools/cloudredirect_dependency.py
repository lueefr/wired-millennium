"""Install the official CloudRedirect release, building its native x64 hook when needed."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from components import api, fetch, write_json, ROOT

REPOSITORY = 'crghofficial/cloudredirect'
BINARIES = ('cloud_redirect.so', 'cloud_redirect_cli')
FILES = (*BINARIES, 'LICENSE')


def arch(path):
    with Path(path).open('rb') as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b'\x7fELF' or header[4] not in (1, 2):
        raise ValueError('Invalid CloudRedirect ELF header')
    if int.from_bytes(header[18:20], 'little') != (3 if header[4] == 1 else 62):
        raise ValueError('Unsupported CloudRedirect architecture')
    return 32 if header[4] == 1 else 64


def verify(directory):
    for filename in BINARIES:
        if arch(Path(directory)/filename) != 64:
            raise ValueError('CloudRedirect must be ELF64 for steamrt64')


def resolve():
    release = api(REPOSITORY+'/releases/latest')
    tag = release['tag_name']
    commit = api(REPOSITORY+'/commits/'+tag)['sha']
    assets = {}
    for filename in BINARIES:
        items = [item for item in release['assets'] if item['name'] == filename]
        if len(items) != 1:
            raise RuntimeError('Official CloudRedirect release is missing '+filename)
        item = items[0]
        digest = item.get('digest') or ''
        if not digest.startswith('sha256:') or len(digest) != 71:
            raise RuntimeError('Official CloudRedirect has no SHA256 for '+filename)
        assets[filename] = {'url':item['browser_download_url'], 'sha256':digest[7:],
                            'id':item['id'], 'updated_at':item.get('updated_at','')}
    return {'repository':REPOSITORY, 'version':tag, 'commit':commit,
            'assets':assets, 'release_url':release['html_url'],
            'release_notes':release.get('body','')[:12000]}


def ensure_posix_header(source):
    """Declare gethostname for recent GCC builds of official CloudRedirect."""
    path = Path(source)/'src/common/stats_store.cpp'
    content = path.read_text()
    if 'gethostname(' not in content or '#include <unistd.h>' in content:
        return
    anchor = '#include <thread>\n'
    if anchor not in content:
        raise RuntimeError('CloudRedirect source changed; cannot apply POSIX header fix')
    path.write_text(content.replace(anchor, anchor+'#include <unistd.h>\n', 1))


def build(info, directory):
    """Only build the exact official release commit; never an unpinned branch."""
    directory = Path(directory)
    source = directory/'source'
    output = directory/'build'
    subprocess.run(['git','clone','--depth','1','--branch',info['version'],
                    'https://github.com/'+REPOSITORY+'.git',str(source)], check=True)
    actual = subprocess.run(['git','-C',str(source),'rev-parse','HEAD'],
                            check=True, capture_output=True, text=True).stdout.strip()
    if actual != info['commit']:
        raise RuntimeError('CloudRedirect release tag changed during download')
    ensure_posix_header(source)
    subprocess.run(['cmake','-S',str(source),'-B',str(output),
                    '-DCMAKE_BUILD_TYPE=Release','-DLINUX_32BIT=OFF',
                    '-DCMAKE_POSITION_INDEPENDENT_CODE=ON'],check=True)
    subprocess.run(['cmake','--build',str(output),'--target','cloud_redirect',
                    'cloud_redirect_cli','--parallel','2'],check=True)
    for filename in BINARIES:
        shutil.copy2(output/filename,directory/filename)
    verify(directory)
    return source/'LICENSE'


def prepare(info,directory):
    """Stage verified official assets; rebuild x64 from pinned sources if assets are i386."""
    if info.get('repository') != REPOSITORY:
        raise ValueError('CloudRedirect repository mismatch')
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    for filename in BINARIES:
        asset = info['assets'][filename]
        fetch(asset['url'],directory/filename,asset['sha256'])
    # A release can still ship the old 32-bit hook despite being offered on x86_64.
    try:
        verify(directory)
    except ValueError as error:
        if 'ELF64' not in str(error):
            raise
        license_file = build(info,directory)
        shutil.copy2(license_file,directory/'LICENSE')
        shutil.rmtree(directory/'source')
        shutil.rmtree(directory/'build')
        method = 'official-source-x64'
    else:
        fetch('https://raw.githubusercontent.com/'+REPOSITORY+'/'+info['commit']+'/LICENSE',
              directory/'LICENSE')
        method = 'official-release'
    (directory/'cloud_redirect.so').chmod(0o755)
    (directory/'cloud_redirect_cli').chmod(0o755)
    (directory/'LICENSE').chmod(0o644)
    return {'repository':REPOSITORY,'version':info['version'],'commit':info['commit'],
            'method':method,'sha256':{filename:hashlib.sha256((directory/filename).read_bytes()).hexdigest()
                                     for filename in FILES}}


def current(info):
    """Reuse an intact already-installed version instead of rebuilding on reinstall."""
    receipt = ROOT/'cloudredirect.json'
    if not receipt.is_file():
        return None
    try:
        record = json.loads(receipt.read_text())
        if record.get('repository') != REPOSITORY or record.get('version') != info['version'] or record.get('commit') != info['commit']:
            return None
        root = Path.home()/'.local/share/CloudRedirect'
        verify(root)
        for filename in FILES:
            path = root/filename
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256'][filename]:
                return None
        return record
    except (OSError, ValueError, KeyError, TypeError):
        return None


def install(info=None, directory=None):
    """Install only after preparation succeeds; preserve the old hook on failure."""
    info = info or resolve()
    if directory is None:
        existing = current(info)
        if existing:
            return existing
        with tempfile.TemporaryDirectory(prefix='wired-cloud-') as temporary:
            prepared = Path(temporary)
            receipt = prepare(info,prepared)
            return install(info,prepared)
    directory = Path(directory)
    verify(directory)
    target = Path.home()/'.local/share/CloudRedirect'
    target.mkdir(parents=True,exist_ok=True)
    old = {}
    try:
        for filename in FILES:
            path = target/filename
            if path.is_symlink():
                raise RuntimeError('Refusing to overwrite a CloudRedirect symlink')
            old[filename] = path.read_bytes() if path.exists() else None
        for filename in FILES:
            path = target/filename
            if old[filename] is not None:
                shutil.copy2(path,path.with_suffix(path.suffix+'.wired-backup'))
            staged = target/(filename+'.wired-new')
            shutil.copy2(directory/filename,staged)
            staged.chmod(0o644 if filename=='LICENSE' else 0o755)
            staged.replace(path)
        result = {'repository':REPOSITORY, 'version':info['version'],
                  'commit':info['commit'],
                  'sha256':{name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in FILES},
                  'restart_required':True}
        write_json(ROOT/'cloudredirect.json',result)
        return result
    except Exception:
        for filename, data in old.items():
            path = target/filename
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)
        raise
