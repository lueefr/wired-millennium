#!/usr/bin/env python3
"""Enable Wired in Millennium's saved plugin list while Steam is stopped."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile


def enable(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Millennium config.json is missing or is a symbolic link")
    original = path.read_text(encoding='utf-8')
    try:
        settings = json.loads(original)
    except json.JSONDecodeError as error:
        raise RuntimeError("Millennium config.json is invalid; refusing to overwrite it") from error
    if not isinstance(settings, dict):
        raise RuntimeError("Millennium config.json must contain an object")
    plugins = settings.setdefault('plugins', {})
    if not isinstance(plugins, dict):
        raise RuntimeError("Millennium plugins settings are invalid")
    enabled = plugins.setdefault('enabledPlugins', [])
    if not isinstance(enabled, list) or any(not isinstance(item, str) for item in enabled):
        raise RuntimeError("Millennium enabledPlugins must be an array of strings")
    if 'wired-millennium' in enabled:
        print('Wired is already enabled in Millennium')
        return False

    enabled.append('wired-millennium')
    # Preserve the previous configuration before replacing it atomically.
    backup = path.with_name('config.json.wired-backup')
    if not backup.exists():
        shutil.copy2(path, backup)
    descriptor, temporary = tempfile.mkstemp(prefix='.wired-config-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Wired enabled in Millennium; existing plugin settings preserved')
    print('Configuration backup:', backup)
    return True


def main():
    parser = argparse.ArgumentParser(description='Enable Wired in Millennium')
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'millennium/config.json')
    arguments = parser.parse_args()
    try:
        enable(arguments.config)
    except (OSError, RuntimeError) as error:
        parser.exit(1, f'Cannot enable Wired: {error}\n')


if __name__ == '__main__':
    main()
