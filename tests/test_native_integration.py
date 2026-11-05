import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import moon

class NativeIntegrationTests(unittest.TestCase):
    def test_import_normalizes_and_remove_preserves_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);steam=root/'steam';steam.mkdir();data=root/'data'
            archive=root/'game.zip'
            with zipfile.ZipFile(archive,'w') as bundle:
                bundle.writestr('123.lua','addappid(123)\naddappid(124, 1, "'+ 'a'*64+'")\nos.execute("bad")\nsetManifestid(124, "999")\n')
                bundle.writestr('124_999.manifest',b'manifest')
            with patch.object(moon,'ROOT',data),patch.object(moon,'steam_root',return_value=steam):
                moon.import_package(archive,123)
                script=steam/'config/stplug-in/123.lua'
                self.assertNotIn('os.execute',script.read_text())
                self.assertIn('setManifestid',script.read_text())
                moon.remove_integration(123)
                self.assertFalse(script.exists())
                self.assertEqual((steam/'depotcache/124_999.manifest').read_bytes(),b'manifest')

    def test_fixes_eligibility_requires_added_and_fully_installed(self):
        import steam_paths
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);steam=root/'steam';(steam/'steamapps/common/Game').mkdir(parents=True);(steam/'config/stplug-in').mkdir(parents=True)
            manifest=steam/'steamapps/appmanifest_123.acf'
            script=steam/'config/stplug-in/123.lua'
            with patch.object(moon,'ROOT',root/'data'),patch.object(moon,'steam_root',return_value=steam),patch.object(steam_paths,'steam_root',return_value=steam):
                app=moon.status([123])['apps']['123'];self.assertFalse(app['added']);self.assertFalse(app['installed'])
                script.write_text('addappid(123)')
                manifest.write_text('"AppState" { "appid" "123" "installdir" "Game" "StateFlags" "1026" }')
                app=moon.status([123])['apps']['123'];self.assertTrue(app['added']);self.assertFalse(app['installed'])
                manifest.write_text('"AppState" { "appid" "123" "installdir" "Game" "StateFlags" "4" }')
                app=moon.status([123])['apps']['123'];self.assertTrue(app['added']);self.assertTrue(app['installed'])
                script.unlink()
                app=moon.status([123])['apps']['123'];self.assertFalse(app['added']);self.assertTrue(app['installed'])

    def test_external_script_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);script=root/'steam/config/stplug-in/123.lua';script.parent.mkdir(parents=True);script.write_text('external')
            archive=root/'game.zip'
            with zipfile.ZipFile(archive,'w') as bundle:bundle.writestr('123.lua','addappid(123)')
            with patch.object(moon,'ROOT',root/'data'),patch.object(moon,'steam_root',return_value=root/'steam'):
                with self.assertRaisesRegex(RuntimeError,'external'):moon.import_package(archive,123)
                self.assertEqual(script.read_text(),'external')

    def test_failed_receipt_rolls_back_script_and_manifests(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);steam=root/'steam';steam.mkdir();data=root/'data';(data/'apps').mkdir(parents=True)
            (data/'apps/123.json').write_text(json.dumps({'lua_sha256':'old'}))
            archive=root/'game.zip'
            with zipfile.ZipFile(archive,'w') as bundle:
                bundle.writestr('123.lua','addappid(123)\naddappid(124)');bundle.writestr('124_999.manifest','data')
            with patch.object(moon,'ROOT',data),patch.object(moon,'steam_root',return_value=steam),patch.object(moon,'write_json',side_effect=OSError('disk')):
                with self.assertRaises(OSError):moon.import_package(archive,123)
                self.assertFalse((steam/'config/stplug-in/123.lua').exists())
                self.assertFalse((steam/'depotcache/124_999.manifest').exists())
