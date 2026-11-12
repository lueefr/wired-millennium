"""User systemd timer for fixed 01:00/07:00/13:00/19:00 update checks."""
import os
from pathlib import Path
import pwd
import subprocess

NAMES=('wired-component-updates.service','wired-component-updates.timer')


def unit_directory():return Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'systemd/user'


def real_user_session():
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()==Path.home().resolve() and bool(os.environ.get('XDG_RUNTIME_DIR'))


def command(*args):
    if not real_user_session():return False
    try:return subprocess.run(['systemctl','--user',*args],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15).returncode==0
    except (OSError,subprocess.TimeoutExpired):return False


def install(plugin):
    script=str(Path(plugin).resolve()/'backend/updates.py')
    if any(ch in script for ch in ('\r','\n')):raise ValueError('Invalid update timer path')
    quoted='"'+script.replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    directory=unit_directory();directory.mkdir(parents=True,exist_ok=True)
    service='''# Managed by Wired; checks metadata and applies only previously approved updates.
[Unit]
Description=Wired component update check
[Service]
Type=oneshot
TimeoutStartSec=10min
UMask=0077
ExecStart=/usr/bin/env -u LD_PRELOAD -u LD_AUDIT -u LD_LIBRARY_PATH -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 '''+quoted+''' --check
'''
    if os.environ.get('XDG_DATA_HOME'):
        data=os.environ['XDG_DATA_HOME'].replace('\\','\\\\').replace('"','\\"').replace('%','%%')
        if '\n' in data or '\r' in data:raise ValueError('Invalid update data path')
        service+='Environment="XDG_DATA_HOME='+data+'"\n'
    timer='''# Managed by Wired. Local wall-clock slots never drift after catch-up.
[Unit]
Description=Check SLSsteam Moon and CloudRedirect Moon four times daily
[Timer]
OnCalendar=*-*-* 01,07,13,19:00:00
Persistent=true
AccuracySec=1s
RandomizedDelaySec=0
[Install]
WantedBy=timers.target
'''
    (directory/NAMES[0]).write_text(service);(directory/NAMES[1]).write_text(timer)
    command('daemon-reload')
    enabled=command('enable','--now',NAMES[1])
    if enabled:command('start','--no-block',NAMES[0])
    return enabled


def remove():
    directory=unit_directory()
    if any(path.exists() and not path.read_text().startswith('# Managed by Wired') for path in (directory/name for name in NAMES)):
        raise ValueError('Update timer units were replaced externally; preserving them')
    command('disable','--now',NAMES[1])
    command('stop',NAMES[0])
    for name in NAMES:(directory/name).unlink(missing_ok=True)
    command('daemon-reload')
