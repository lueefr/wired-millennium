"""Integration against the actual installed Millennium Lua host, not a Lua mock."""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
import unittest
try:
    import msgpack
except ImportError:
    msgpack = None

HOST = Path('/usr/lib/millennium/libmillennium_luavm_x86')
BACKEND = Path(__file__).resolve().parents[1]/'backend'


@unittest.skipUnless(msgpack and HOST.exists(), 'Requires the Millennium Lua host and msgpack in the test environment')
class MillenniumHostTests(unittest.TestCase):
    def test_real_lua_load_rpc_settings_and_shutdown(self):
        with tempfile.TemporaryDirectory(prefix='wired-native-') as temporary:
            root = Path(temporary)
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(str(root/'parent.sock')); listener.listen(1); listener.settimeout(15)
            env = dict(os.environ, XDG_RUNTIME_DIR=str(root), XDG_DATA_HOME=str(root/'data'))
            for key in ('LD_PRELOAD','LD_AUDIT','LD_LIBRARY_PATH','PYTHONHOME'):
                env.pop(key, None)
            process = subprocess.Popen([str(HOST), str(root/'parent.sock')], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            conn = None
            logs = []; ready = []
            def send(value):
                payload = msgpack.packb(value, use_bin_type=True)
                conn.sendall(struct.pack('<I',len(payload))+payload)
            def receive_exact(count):
                data=b''
                while len(data)<count:
                    chunk=conn.recv(count-len(data))
                    if not chunk: raise RuntimeError('Lua host disconnected')
                    data+=chunk
                return data
            def response(identity):
                while True:
                    size=struct.unpack('<I',receive_exact(4))[0]
                    value=msgpack.unpackb(receive_exact(size), raw=False, strict_map_key=False)
                    if value['type']=='res' and value['id']==identity:
                        return value
                    if value.get('method')=='log':logs.append(value['params'])
                    if value.get('method')=='ready':ready.append(True)
                    if value['type']=='req':
                        send({'type':'res','id':value['id'],'result':True})
            def rpc(identity, method, args=None):
                send({'type':'req','id':identity,'method':'evaluate','params':{'methodName':'WiredRPC','argumentList':[json.dumps({'method':method,'args':args or {}})]}})
                result=response(identity)
                self.assertNotIn('error',result)
                self.assertTrue(result['result']['success'],result)
                return json.loads(result['result']['value'])
            try:
                conn,_=listener.accept();conn.settimeout(20)
                send({'type':'req','id':100,'method':'init','params':{'plugin_name':'wired-millennium','backend_dir':str(BACKEND),'backend_file':str(BACKEND/'main.lua'),'steam_path':str(root/'Steam'),'crash_dump_dir':str(root/'dumps'),'steam_pid':os.getpid()}})
                init=response(100)
                self.assertNotIn('error',init)
                self.assertTrue(ready,'Lua on_load never called millennium.ready(): '+str(logs))
                config=rpc(101,'GetSettings')
                self.assertIn('accela_settings',config)
                self.assertTrue(rpc(102,'SaveSettings',{'settings_json':json.dumps({'api_list':[],'accela_settings':{'max_downloads':5}})})['success'])
                self.assertEqual(rpc(103,'GetSettings')['accela_settings']['max_downloads'],5)
                status=rpc(104,'GetStatus'); self.assertEqual(status['jobs'],[])
                bad=rpc(105,'ForbiddenMethod'); self.assertFalse(bad['success'])
                self.assertFalse(rpc(107,'OpenFixes',{'appid':0})['success'])
                self.assertFalse(rpc(108,'OpenFixes',{'appid':4294967295})['success'])
                self.assertIn('ForbiddenMethod', json.dumps(logs), 'RPC failures must reach the native Millennium logger')
                send({'type':'req','id':106,'method':'shutdown','params':{}}); response(106)
                conn.close();conn=None
                process.wait(timeout=10)
                self.assertEqual(process.returncode,0,process.stderr.read().decode())
                ipc=root/('wired-'+str(process.pid))/'rpc.sock'
                deadline=time.monotonic()+5
                while ipc.exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertFalse(ipc.exists(),'Service socket survived Lua host shutdown')
            finally:
                if conn:conn.close()
                listener.close()
                if process.poll() is None:process.terminate();process.wait(timeout=10)
                process.stderr.close()


if __name__=='__main__':unittest.main()
