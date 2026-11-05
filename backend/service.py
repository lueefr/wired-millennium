"""Private Unix-socket adapter between Millennium Lua and the Python job engine."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import struct
import sys
import threading
import time
from diagnostics import emit, drain

MAX_REQUEST = 2*1024*1024
METHODS = {'GetLanguage', 'GetSettings', 'SaveSettings', 'GetStatus', 'StartDownload', 'StartTask', 'PrepareComponents', 'ReplyPrompt', 'Cancel', 'Pause', 'Resume', 'MoveJob', 'GetIntegrationState', 'GetLuaToolsAuthStatus', 'StartLuaToolsLogin', 'CancelLuaToolsLogin', 'LogoutLuaTools', 'CloudStatus', 'CloudAuthorize', 'CloudAuthPoll', 'CloudDiscard'}


def exchange(directory, payload):
    path = str(Path(directory)/'rpc.sock')
    deadline = time.monotonic()+8
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10)
        while True:
            try:
                client.connect(path)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Wired internal service did not start; see service.log")
                time.sleep(.05)
        client.sendall(json.dumps(payload).encode()+b'\n')
        with client.makefile('rb') as stream:
            data = stream.readline(MAX_REQUEST+1)
        if not data or len(data) > MAX_REQUEST:
            raise RuntimeError("Invalid response from internal service")
        return json.loads(data)


def serve(directory, parent):
    os.umask(0o077)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise RuntimeError("Invalid IPC directory")
    directory.chmod(0o700)
    path = directory/'rpc.sock'
    import api
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            uid = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
            if uid != os.getuid():
                return
            self.request.settimeout(10)
            raw = self.rfile.readline(MAX_REQUEST+1)
            if not raw or len(raw) > MAX_REQUEST:
                return
            shutdown = False
            method = "request"
            try:
                payload = json.loads(raw)
                method = payload['method']
                args = payload.get('args', {})
                if not isinstance(args, dict):
                    raise ValueError("Invalid arguments")
                if method == 'Ping':
                    value = {'success': True, 'version': '0.7.0'}
                elif method == 'Shutdown':
                    value = {'success': True}; shutdown = True
                elif method in METHODS:
                    result = getattr(api, method)(**args)
                    value = json.loads(result) if isinstance(result, str) else result
                else:
                    raise ValueError("Method not allowed")
            except Exception as exc:
                value = {'success': False, 'error': str(exc)}
            if isinstance(value, dict):
                if value.get('success') is False:
                    emit(method+': '+str(value.get('error', "Operation refused")), 'error')
                value['_wired_logs'] = drain()
            self.wfile.write(json.dumps(value, ensure_ascii=False).encode()+b'\n')
            self.wfile.flush()
            if shutdown:
                threading.Thread(target=self.server.shutdown, daemon=True).start()
    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
    # Each Lua host has its own private directory; avoid unlinking another server.
    if path.exists():
        raise RuntimeError("Wired socket already exists")
    with Server(str(path), Handler) as server:
        def watch_parent():
            while True:
                time.sleep(1)
                try:
                    os.kill(parent, 0)
                except ProcessLookupError:
                    server.shutdown(); return
        threading.Thread(target=watch_parent, daemon=True).start()
        def shutdown(*args):
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, shutdown)
        try:
            server.serve_forever(poll_interval=.1)
        finally:
            api.manager.close()
            api.manager.thread.join(3)
            path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('serve', 'client', 'ping'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('--request', type=Path)
    parser.add_argument('--parent', type=int, default=os.getppid())
    args = parser.parse_args()
    if args.mode == 'serve':
        serve(args.directory, args.parent)
        return
    if args.mode == 'ping':
        result = exchange(args.directory, {'method': 'Ping'})
    else:
        if not args.request or args.request.parent.resolve() != args.directory.resolve() or args.request.is_symlink():
            raise ValueError("Invalid request file")
        try:
            args.request.chmod(0o600)
            if args.request.stat().st_size > MAX_REQUEST:
                raise ValueError("Request too large")
            payload = json.loads(args.request.read_text())
            result = exchange(args.directory, payload)
        finally:
            args.request.unlink(missing_ok=True)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'success': False, 'error': str(exc)}))
        sys.exit(1)
