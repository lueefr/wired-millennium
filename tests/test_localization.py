import json
from pathlib import Path
import re
import unittest

DIRECTORY=Path(__file__).resolve().parents[1]/'locales'


class LocalizationTests(unittest.TestCase):
    def test_all_steam_languages_have_complete_catalogs(self):
        languages=json.loads((DIRECTORY/'languages.json').read_text())
        english=json.loads((DIRECTORY/'en.json').read_text())
        self.assertEqual(len(languages),31)
        self.assertEqual(languages['brazilian'],'pt-BR');self.assertEqual(languages['portuguese'],'pt')
        self.assertEqual(languages['latam'],'es-419');self.assertEqual(languages['schinese'],'zh-CN')
        for language in languages.values():
            catalog=json.loads((DIRECTORY/(language+'.json')).read_text())
            self.assertEqual(set(catalog),set(english),language)
            for key,value in catalog.items():
                self.assertIsInstance(value,str);self.assertTrue(value.strip(),(language,key))
                self.assertEqual(sorted(re.findall(r'\{\w+\}',key)),sorted(re.findall(r'\{\w+\}',value)),(language,key))
                self.assertNotRegex(value,r'WIRED_\d+|ZXQ\d+QXZ')

    def test_build_bundles_catalogs(self):
        build=(DIRECTORY.parent/'tools/build.py').read_text()
        self.assertIn('WIRED_LOCALES',build);self.assertIn('WIRED_LANGUAGES',build)

    def test_backend_callback_uses_steam_language(self):
        import sys
        from unittest.mock import patch
        sys.path.insert(0,str(DIRECTORY.parent/'backend'))
        import localization
        with patch.object(localization,'steam_language',return_value='brazilian'):
            text='Login completed. Return to Steam.'
            expected=json.loads((DIRECTORY/'pt-BR.json').read_text())[text]
            self.assertEqual(localization.t(text),expected)
