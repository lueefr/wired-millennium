"""Bounded diagnostic events forwarded to Millennium's native Lua logger."""
from collections import deque
import re
import threading

_events = deque(maxlen=400)
_lock = threading.Lock()


def redact(message):
    text = str(message)
    text = re.sub(r'https?://[^\s<>\"\']+', '[URL omitted]', text)
    text = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer [hidden]', text)
    text = re.sub(r'\bsmm_[A-Za-z0-9_-]+', '[key hidden]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[token hidden]', text)
    text = re.sub(r'(?i)((?:api[_ -]?key|access_token|refresh_token|password|authorization|client_secret)\s*[=:]\s*)[^\s,;]+', r'\1[hidden]', text)
    return text.replace('\n', ' ').replace('\r', ' ')[:2000]


def emit(message, level='info'):
    with _lock:
        _events.append({'level': level, 'message': redact(message)})


def drain():
    with _lock:
        events = list(_events)
        _events.clear()
        return events
