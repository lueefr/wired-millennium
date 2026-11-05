import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import cloud

class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.patch=patch.object(cloud,'CONFIG',self.root/'cloud/config.json');self.patch.start()
    def tearDown(self):
        cloud.discard();self.patch.stop();self.temporary.cleanup()

    def test_draft_tokens_activity_and_restart_rollback(self):
        cfg={'provider':'local','custom_key':'preserved','sync_achievements':False}
        cloud.write(cloud.CONFIG,cfg)
        token=cloud.token_path('gdrive');stage=token.with_suffix('.pending')
        cloud.write(stage,{'refresh_token':'private-refresh','access_token':'private-access'})
        cloud.STAGED['gdrive']=stage
        self.assertFalse(cloud.status()['providers']['gdrive']['authenticated'])
        self.assertTrue(cloud.status()['providers']['gdrive']['pending'])
        self.assertNotIn('private-',json.dumps(cloud.status()))
        request={'provider':'gdrive','sync_activity':True}
        with self.assertRaises(RuntimeError):cloud.apply(request,restart=lambda:False)
        self.assertEqual(cloud.config(),cfg);self.assertFalse(token.exists());self.assertTrue(stage.exists())
        cloud.apply(request,restart=lambda:True)
        current=cloud.config()
        for key in ('stats_sync_enabled','sync_achievements','sync_playtime'):self.assertIs(current[key],True)
        self.assertEqual(current['custom_key'],'preserved');self.assertEqual(current['provider'],'gdrive')
        self.assertEqual(token.stat().st_mode&0o777,0o600);self.assertFalse(stage.exists())

    def test_static_credentials_probe_and_migration_rollback(self):
        cloud.write(cloud.CONFIG,{'provider':'folder','sync_folder_path':str(self.root/'saves')})
        credentials={'account_id':'account','access_key_id':'access','secret_access_key':'private-secret','bucket':'bucket'}
        request={'provider':'r2','credentials':credentials,'sync_activity':True,'migrate':True}
        with patch.object(cloud,'cli',side_effect=RuntimeError('probe failed')):
            with self.assertRaises(RuntimeError):cloud.apply(request,restart=lambda:True)
        self.assertEqual(cloud.config()['provider'],'folder');self.assertFalse(cloud.token_path('r2').exists())
        with patch.object(cloud,'cli',return_value={}) as cli:
            cloud.apply(request,restart=lambda:True)
            self.assertEqual(cli.call_args_list[0].args,('list-remote-app-ids',['r2',0]))
            self.assertEqual(cli.call_args_list[1].args,('migrate',['folder','r2']))
        self.assertNotIn('private-secret',json.dumps(cloud.status()))
        self.assertTrue(cloud.status()['providers']['r2']['settings']['has_secret'])

    def test_paths_and_local_inventory_match_lumen(self):
        cfg={'provider':'gdrive','token_path':'../../outside'}
        self.assertEqual(cloud.token_path('gdrive',cfg),cloud.CONFIG.parent/'tokens_gdrive.json')
        app=cloud.CONFIG.parent/'storage/42/123';(app/'nested').mkdir(parents=True)
        (app/'state.cloudredirect').write_bytes(b'metadata');(app/'save.dat').write_bytes(b'save');(app/'nested/state.cloudredirect').write_bytes(b'game')
        (app/'link').symlink_to(self.root)
        with patch.object(cloud,'steam_root',side_effect=RuntimeError('absent')):inventory=cloud.local_apps()
        self.assertEqual(inventory['apps'][0]['files'],2);self.assertEqual(inventory['apps'][0]['size'],8)
        self.assertEqual(inventory['accounts'][0]['id'],42)

    def test_oauth_stages_tokens_and_rejects_wrong_state(self):
        with patch.object(cloud,'oauth_exchange',return_value={'access_token':'private-access','refresh_token':'private-refresh','expires_at':1000}) as exchange:
            start=cloud.authorize('gdrive');query=urllib.parse.parse_qs(urllib.parse.urlsplit(start['auth_url']).query)
            redirect=query['redirect_uri'][0]
            self.assertTrue(redirect.startswith('http://localhost:'))
            self.assertEqual(query['scope'],['https://www.googleapis.com/auth/drive.file'])
            self.assertEqual(query['access_type'],['offline'])
            try:urllib.request.urlopen(redirect+'?code=test&state=wrong',timeout=5)
            except urllib.error.HTTPError as error:error.close()
            else:self.fail('Wrong state accepted')
            self.assertFalse(exchange.called)
            with urllib.request.urlopen(redirect+'?'+urllib.parse.urlencode({'code':'test','state':query['state'][0]}),timeout=5) as response:self.assertEqual(response.status,200)
            self.assertEqual(cloud.auth_poll()['status'],'done')
            self.assertIn('gdrive',cloud.STAGED);self.assertFalse(cloud.token_path('gdrive').exists())
            self.assertNotIn('private-',json.dumps(cloud.auth_poll()))
            self.assertFalse(cloud.CONFIG.exists())
