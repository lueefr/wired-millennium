import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.parse
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import providers

class ProviderTests(unittest.TestCase):
    def test_pkce_callback_private_session_and_logout(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(providers,'SESSION',Path(temporary)/'session.json'),patch.object(providers,'post',return_value={'access_token':'private-access','refresh_token':'private-refresh','expires_in':3600,'user':{'user_metadata':{'name':'Example'}}}) as post:
            try:
                start=providers.begin_login()
                url=urllib.parse.urlsplit(start['auth_url']);query=urllib.parse.parse_qs(url.query)
                self.assertEqual(url.hostname,'db.lua.tools');self.assertEqual(query['provider'],['discord'])
                with urllib.request.urlopen('http://127.0.0.1:53789/callback?code=test-code',timeout=5) as response:self.assertIn('Login',response.read().decode())
                call=post.call_args
                self.assertEqual(call.args[0],'/token?grant_type=pkce')
                verifier=call.args[1]['code_verifier']
                challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
                self.assertEqual(query['code_challenge'],[challenge])
                status=providers.status();self.assertTrue(status['configured']);self.assertEqual(status['account'],'Example')
                self.assertNotIn('private-',json.dumps(status))
                self.assertEqual(providers.SESSION.stat().st_mode&0o777,0o600)
                self.assertEqual(providers.access_token(),'private-access')
                providers.logout();self.assertFalse(providers.SESSION.exists())
            finally:providers.cancel()

    def test_expired_session_refreshes_before_manifest(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(providers,'SESSION',Path(temporary)/'session.json'):
            providers.SESSION.write_text(json.dumps({'access_token':'old','refresh_token':'refresh','expires_at':0}))
            with patch.object(providers,'post',return_value={'access_token':'renewed','expires_in':3600}) as post:
                self.assertEqual(providers.access_token(),'renewed')
                post.assert_called_once_with('/token?grant_type=refresh_token',{'refresh_token':'refresh'})
                self.assertEqual(json.loads(providers.SESSION.read_text())['refresh_token'],'refresh')

    def test_candidates_respect_preferences(self):
        with patch.object(providers,'access_token',return_value='private-token'):
            sources=providers.candidates({})
            self.assertEqual([source['name'] for source in sources],['Luie (lua.tools)','Sushi'])
            self.assertIn('source=Luie',sources[0]['url'])
            self.assertEqual(providers.candidates({'providers':{'lua_tools':False,'sushi':False}}),[])
            ryuu=providers.candidates({'providers':{'lua_tools':False,'sushi':False,'ryuu':True}})
            self.assertEqual(ryuu[0]['name'],'Ryuu')
        with self.assertRaises(ValueError):providers.fetch_manifest('http://example.com/123',{},True)
        with self.assertRaises(ValueError):providers.fetch_manifest('http://167.235.229.108/123',{'Authorization':'secret'},True)
