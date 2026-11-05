"""Fetch the pinned Lumen restart helper without redistributing its source."""
import hashlib
from pathlib import Path
import urllib.request

COMMIT = '52475c3ec0bbe2bf0ccdd209d86a40d99a9881fa'
SHA256 = '5692d99f216e3e853e6006ec02c790b7b69127de7fb076eb01b2cc1065dd6962'
URL = f'https://raw.githubusercontent.com/swwayps/lumen/{COMMIT}/lua/restart_steam.sh'


def ensure(root):
    destination = Path(root)/'backend/restart_steam.sh'
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == SHA256:
        return destination
    with urllib.request.urlopen(URL, timeout=30) as response:
        content = response.read(1024*1024)
    if hashlib.sha256(content).hexdigest() != SHA256:
        raise RuntimeError('The pinned Lumen restart helper failed checksum verification')
    destination.write_bytes(content)
    destination.chmod(0o755)
    return destination
