"""Extract ACCELA's shipped Python sources/runtime without running its launcher."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from components import ROOT, write_json


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_runtime(progress=lambda message: None):
    manifest_path = ROOT/'prepared.json'
    if not manifest_path.exists():
        raise RuntimeError('Prepare the components before using the internal engine')
    manifest = json.loads(manifest_path.read_text())
    artifact = manifest['components']['accela']
    expected = artifact['sha256'][artifact['asset']]
    destination = ROOT/'engines'/expected
    marker = destination/'engine.json'
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT/'engine.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if marker.exists():
            return json.loads(marker.read_text())
        extractor = shutil.which('7z') or shutil.which('7zz')
        if not extractor:
            raise RuntimeError('Install 7zip (7z or 7zz) to extract the internal engine')
        archive = Path(manifest['directory'])/'accela'/artifact['asset']
        progress("Checking the ACCELA package")
        if sha256(archive) != expected:
            raise RuntimeError("The prepared ACCELA package has been changed")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            stage = Path(temporary)
            image = stage/'ACCELA.AppImage'
            with tarfile.open(archive) as package:
                member = package.getmember('bin/ACCELA.AppImage')
                if not member.isfile():
                    raise RuntimeError("AppImage is not a regular file")
                with package.extractfile(member) as source, image.open('wb') as target:
                    shutil.copyfileobj(source, target)
            progress("Extracting sources and Python from ACCELA; no windows will open")
            # Do not execute AppImage, AppRun, run.sh or main.py.
            result = subprocess.run([extractor, 'x', '-y', str(image), 'bin/src/*', 'bin/.venv/*', '-xr!terminfo', '-o'+str(stage/'files')], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if result.returncode:
                raise RuntimeError("Failed to extract AppImage:" + result.stdout[-2000:])
            files = stage/'files'
            for link in files.rglob('*'):
                if link.is_symlink() and not link.resolve().is_relative_to(files.resolve()):
                    raise RuntimeError('External runtime link: ' + str(link.relative_to(files)))
            source = files/'bin/src'
            python = files/'bin/.venv/bin/python3'
            if not python.is_file() or not (source/'core/tasks/process_zip_task.py').is_file():
                raise RuntimeError("ACCELA layout incompatible with adapter")
            version = (source/'res/version').read_text().strip()
            # Generate an inventory, without redistributing upstream sources in the Git repo.
            inventory = {str(p.relative_to(source)): sha256(p) for p in source.rglob('*.py')}
            info = {'version': version, 'artifact_sha256': expected, 'source': str(destination/'bin/src'), 'python': str(destination/'bin/.venv/bin/python3'), 'source_hashes': inventory}
            write_json(files/'engine.json', info)
            image.unlink()
            files.rename(destination)
        return info


def runtime_env():
    env = os.environ.copy()
    for name in ('LD_AUDIT', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'APPIMAGE', 'APPDIR', 'PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        env.pop(name, None)
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


if __name__ == '__main__':
    print(json.dumps(ensure_runtime(print), indent=2))
