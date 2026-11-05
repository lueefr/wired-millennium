#!/usr/bin/env python3
"""Install/update the Lua Millennium adapter and built frontend, preserving old files."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--plugins-dir', type=Path, default=Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share')))/'millennium/plugins')
parser.add_argument('--plugin-only', action='store_true', help="Update plugin files only (development)")
parser.add_argument('--update', action='store_true', help='Atualizar Wired existente, mantendo backup')
args = parser.parse_args()
source = Path(__file__).resolve().parent
target = args.plugins_dir.expanduser()/'wired-millennium'
if target.exists():
    if not args.update:
        parser.error("Wired already installed; use --update to update with backup")
    if target.is_symlink() or json.loads((target/'plugin.json').read_text()).get('name') != 'wired-millennium':
        parser.error("Destination does not belong to Wired")
if not args.plugin_only:
    sys.path.insert(0, str(source/'tools'))
    from slsteam_dependency import install
    install()
    sys.path.insert(0, str(source/'backend'))
    from components import update_cloud
    update_cloud(print)
sys.path.insert(0, str(source/'tools'))
from upstream_helpers import ensure
ensure(source)
subprocess.run([sys.executable, str(source/'tools/build.py')], check=True)
target.parent.mkdir(parents=True, exist_ok=True)
backup = None
with tempfile.TemporaryDirectory(prefix='.wired-stage-', dir=target.parent) as temporary:
    staged = Path(temporary)/'wired-millennium'
    staged.mkdir()
    for name in ('backend', 'public', 'locales', '.millennium', 'plugin.json'):
        item = source/name
        if item.is_dir():
            shutil.copytree(item, staged/name, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copy2(item, staged/name)
    if target.exists():
        data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share')))/'wired-millennium/plugin-backups'
        data.mkdir(parents=True, exist_ok=True)
        backup = data/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        shutil.move(str(target), backup)
    try:
        staged.rename(target)
    except Exception:
        if backup:
            shutil.move(str(backup), target)
        raise
print(f'Wired installed at {target}. Restart Steam and enable Wired in Millennium.')
if backup:
    print(f'Previous backup: {backup}')
