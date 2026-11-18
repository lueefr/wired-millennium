"""Bounded, credential-redacted diagnostics from Wired and native Steam components."""
from collections import deque
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import re
import threading

_events = deque(maxlen=2500)
_pending = deque(maxlen=400)
_cursors = {}
_lock = threading.RLock()
_serial = 0
_MAX_LINE = 3500
_MAX_READ = 128 * 1024
_MAX_FILES = 40
_SECRET = re.compile(
    r'''(?i)(["']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|id_token|'''
    r'''password|authorization|client_secret|secret_access_key|private_key|'''
    r'''cookie|session_token|steam_login_secure)["']?\s*[:=]\s*)'''
    r'''(?:"[^"]*"|'[^']*'|[^,;\s}\]]+)'''
)


def redact(message):
    text = str(message).replace('\x00', '')
    text = re.sub(r'https?://[^\s<>"\']+', '[URL omitted]', text)
    text = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer [hidden]', text)
    text = re.sub(r'\bsmm_[A-Za-z0-9_-]+', '[key hidden]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[token hidden]', text)
    text = _SECRET.sub(lambda match: match.group(1)+'[hidden]', text)
    return text[:_MAX_LINE]


def _level(line):
    if re.search(r'(?i)\b(error|failed|failure|fatal|exception|traceback|critical|segfault|crash)\b', line):
        return 'error'
    if re.search(r'(?i)\b(warn(?:ing)?|timeout|retry|denied|unavailable)\b', line):
        return 'warning'
    if re.search(r'(?i)\b(debug|trace)\b', line):
        return 'debug'
    return 'info'


def _add(message, level, source, forwarded=False):
    global _serial
    _serial += 1
    entry = {
        'id': _serial, 'time': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        'source': str(source)[:100], 'level': level if level in ('error', 'warning', 'info', 'debug') else 'info',
        'message': redact(message)
    }
    _events.append(entry)
    if forwarded:
        _pending.append({'level': entry['level'], 'message': entry['message'][:2000]})


def emit(message, level='info', source='Wired'):
    with _lock:
        _add(message, level, source, forwarded=True)


def drain():
    """Millennium logger forwarding is independent from the retained log view."""
    with _lock:
        result = list(_pending)
        _pending.clear()
        return result


def _roots():
    home = Path.home()
    data = Path(os.environ.get('XDG_DATA_HOME') or home/'.local/share')
    state = Path(os.environ.get('XDG_STATE_HOME') or home/'.local/state')
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home/'.config')
    own = data/'wired-millennium'
    return [
        ('Millennium', state/'millennium/logs', 'all'),
        ('Millennium', data/'millennium/logs', 'all'),
        ('Millennium', home/'.millennium/logs', 'all'),
        ('CloudRedirect', config/'CloudRedirect', 'component'),
        ('CloudRedirect', config/'CloudRedirect/logs', 'all'),
        ('SLSsteam', config/'SLSsteam', 'component'),
        ('SLSsteam', data/'SLSsteam', 'component'),
        ('Steam Cloud', data/'Steam/logs', 'steam'),
        ('Wired', own, 'wired'),
        ('Wired Service', own/'ipc', 'ipc'),
    ]


def _allowed(path, mode):
    name = path.name.lower()
    if mode == 'component':
        return (name.endswith(('.log', '.log.txt')) or name in ('cloud_log.txt', 'cr_debug.txt'))
    if mode == 'steam':
        return name in ('cloud_log.txt', 'cloud_log.log', 'cef_log.txt')
    if mode == 'wired':
        return name in ('component-update-worker.log', 'wired.log', 'service.log')
    if mode == 'ipc':
        return name == 'service.log'
    return name.endswith(('.log', '.log.txt', '.txt'))


def _discover():
    candidates = []
    for source, root, mode in _roots():
        if root.is_symlink() or not root.is_dir():
            continue
        try:
            if mode == 'ipc':
                children = [folder/'service.log' for folder in root.iterdir()
                            if folder.name.startswith('wired-') and folder.is_dir()
                            and not folder.is_symlink()]
            else:
                children = list(root.iterdir())
            for path in children:
                if path.is_symlink() or not _allowed(path, mode) or not path.is_file():
                    continue
                stat = path.stat()
                if stat.st_uid != os.getuid():
                    continue
                candidates.append((stat.st_mtime, source, path, stat))
        except OSError:
            continue
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[:_MAX_FILES]


def _scan():
    sources = []
    active = set()
    for _, source, path, stat in _discover():
        key = str(path)
        active.add(key)
        label = source+' / '+path.name
        sources.append({'source': label, 'path': key, 'bytes': stat.st_size,
                        'updated': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()})
        previous = _cursors.get(key)
        identity = (stat.st_dev, stat.st_ino)
        if previous and previous[0] == identity and stat.st_size >= previous[1]:
            offset, carry = previous[1], previous[2]
        else:
            offset, carry = max(0, stat.st_size-_MAX_READ), b''
        if offset == stat.st_size:
            continue
        if stat.st_size-offset > _MAX_READ:
            offset, carry = stat.st_size-_MAX_READ, b''
        try:
            with path.open('rb') as stream:
                stream.seek(offset)
                data = stream.read(_MAX_READ)
        except OSError:
            continue
        if offset > 0 and not carry and (not previous or previous[0] != identity or stat.st_size-previous[1] > _MAX_READ):
            data = data.partition(b'\n')[2]  # Drop the potentially truncated first line.
        chunk = carry+data
        lines = chunk.split(b'\n')
        tail = lines.pop()
        _cursors[key] = (identity, offset+len(data)+(0 if not (offset > 0 and not carry) else 0), tail[-_MAX_LINE:])
        for line in lines:
            value = line.decode('utf-8', errors='replace').strip('\r')
            if value.strip():
                _add(value, _level(value), label)
    # A rotated file starts from its new inode; stale cursors are not retained.
    for key in list(_cursors):
        if key not in active:
            del _cursors[key]
    return sources


def snapshot(after=0, limit=300):
    """Read only allowlisted log files and return a bounded incremental view."""
    if type(after) is not int or after < 0:
        raise ValueError('Invalid log cursor')
    if type(limit) is not int or not 1 <= limit <= 600:
        raise ValueError('Invalid log limit')
    with _lock:
        sources = _scan()
        entries = [entry.copy() for entry in _events if entry['id'] > after]
        if after == 0 or len(entries) > limit:
            entries = entries[-limit:]
        return {
            'entries': entries, 'cursor': _serial, 'sources': sources,
            'runtime': {'python': platform.python_version(), 'pid': os.getpid(),
                        'architecture': platform.machine(), 'plugin': 'Wired 0.8.0'},
            'total_retained': len(_events)
        }
