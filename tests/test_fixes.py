from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import fixes
import steam_paths

FIX='12345678-1234-1234-1234-123456789012'
class FixTests(unittest.TestCase):
    def test_apply_restore_and_preserve_later_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);game=root/'game';game.mkdir();(game/'original.dll').write_bytes(b'original')
            def download(url,destination,job,manager):
                with zipfile.ZipFile(destination,'w') as bundle:
                    bundle.writestr('original.dll',b'fix');bundle.writestr('new.dll',b'new')
            job={'id':'test','_args':{'appid':123,'fix_id':FIX},'_cancel':threading.Event()}
            entry={'id':FIX,'title':'Test fix','hasFix':True,'requiresPreparation':False}
            with patch.object(fixes,'ROOT',root/'data'),patch.object(fixes,'installed_game',return_value=game),patch.object(fixes,'ensure_closed'),patch.object(fixes,'catalogue',return_value={'fixes':[entry]}),patch.object(fixes,'resolve',return_value='https://example.test/fix'),patch.object(fixes,'fetch',side_effect=download):
                fixes.ROOT.mkdir()
                result=fixes.apply(job,None);self.assertEqual(result['files'],2)
                self.assertEqual((game/'original.dll').read_bytes(),b'fix')
                (game/'original.dll').write_bytes(b'user edit')
                with self.assertRaisesRegex(ValueError,'changed'):fixes.restore(123)
                self.assertEqual((game/'original.dll').read_bytes(),b'user edit')
                (game/'original.dll').write_bytes(b'fix')
                fixes.restore(123)
                self.assertEqual((game/'original.dll').read_bytes(),b'original')
                self.assertFalse((game/'new.dll').exists())
                write_json=fixes.write_json;counter=[0]
                def fail_commit(path,value):
                    counter[0]+=1
                    if counter[0]==2:raise OSError('disk failure')
                    write_json(path,value)
                with patch.object(fixes,'write_json',side_effect=fail_commit):
                    with self.assertRaises(OSError):fixes.apply(job,None)
                self.assertEqual((game/'original.dll').read_bytes(),b'original')
                self.assertFalse((game/'new.dll').exists())


    def test_unsafe_fix_preserves_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);game=root/'game';game.mkdir()
            def download(url,destination,job,manager):
                with zipfile.ZipFile(destination,'w') as bundle:bundle.writestr('../outside','bad')
            entry={'id':FIX,'title':'Bad fix','hasFix':True,'requiresPreparation':False}
            with patch.object(fixes,'ROOT',root/'data'),patch.object(fixes,'installed_game',return_value=game),patch.object(fixes,'ensure_closed'),patch.object(fixes,'catalogue',return_value={'fixes':[entry]}),patch.object(fixes,'resolve',return_value='https://example.test'),patch.object(fixes,'fetch',side_effect=download):
                fixes.ROOT.mkdir()
                with self.assertRaises(ValueError):fixes.apply({'id':'test','_args':{'appid':123,'fix_id':FIX},'_cancel':threading.Event()},None)
                self.assertFalse((root/'outside').exists());self.assertEqual(list(game.iterdir()),[])

    def test_installation_resolved_from_steam_acf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);apps=root/'steamapps';(apps/'common/Game').mkdir(parents=True)
            acf=apps/'appmanifest_123.acf';acf.write_text('"AppState" { "appid" "123" "installdir" "Game" }')
            with patch.object(steam_paths,'steam_root',return_value=root):
                self.assertEqual(steam_paths.installed_game(123),apps/'common/Game')
                acf.write_text('"AppState" { "appid" "123" "installdir" "../../outside" }')
                with self.assertRaises(ValueError):steam_paths.installed_game(123)
