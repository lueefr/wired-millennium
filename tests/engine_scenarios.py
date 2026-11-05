"""Runs under bundled Python against real extracted ACCELA modules, entirely offline."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

BACKEND = Path(__file__).resolve().parents[1]/'backend'
sys.path.insert(0, str(BACKEND))
import engine_worker as worker

SOURCE = Path(sys.argv[1])
# unittest must not interpret our source path as a test name.
sys.argv = [sys.argv[0]]


class EngineScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory(prefix='wired-integration-')
        cls.home = Path(cls.root.name)
        os.environ['HOME'] = str(cls.home)
        os.environ['XDG_CONFIG_HOME'] = str(cls.home/'.config')
        os.environ['TMPDIR'] = str(cls.home/'tmp')
        (cls.home/'tmp').mkdir()
        tempfile.tempdir = None
        cls.engine = worker.Engine(SOURCE, {}, cls.home/'state')

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=self.home)
        self.addCleanup(self.directory.cleanup)
        self.case = Path(self.directory.name)
        self.library = self.case/'Steam'
        (self.library/'steamapps/common').mkdir(parents=True)
        self.config = self.case/'config.yaml'
        self.engine.settings.values = dict(worker.DEFAULTS)
        self.engine.handler.errors.clear()
        self.engine.handler.secrets.clear()
        # Every external service and tool is replaced, while ACCELA parsing,
        # command construction, YAML edits, manifests and library scans run for real.
        from core.tasks import process_zip_task, download_depots_task
        from core import steam_helpers
        from utils import yaml_config_manager, helpers
        from managers import game_manager
        self.patches = [
            patch.object(process_zip_task, 'get_depot_info_from_api', return_value={'installdir': 'Example', 'buildid': '1', 'depots': {'124': {'size': 12, 'oslist': 'linux'}}}),
            patch.object(steam_helpers, 'get_steam_libraries', return_value=[str(self.library)]),
            patch.object(steam_helpers, 'find_steam_install', return_value=str(self.library)),
            patch.object(game_manager, 'get_steam_libraries', return_value=[str(self.library)]),
            patch.object(game_manager, 'find_steam_install', return_value=str(self.library)),
            patch.object(yaml_config_manager, 'get_user_config_path', return_value=self.config),
            patch.object(helpers, 'ensure_dotnet_availability', return_value=True),
            patch.object(download_depots_task, 'get_dotnet_path', return_value=sys.executable),
        ]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)
        self.archive = self.case/'123.zip'
        with zipfile.ZipFile(self.archive, 'w') as bundle:
            bundle.writestr('123.lua', 'addappid(123) -- Example\naddappid(124, 1, "'+'0'*64+'") -- Linux\naddappid(125) -- Bonus\naddtoken(123, "123456789")\n')
            bundle.writestr('124_999.manifest', b'example')

    def download(self, fail=False, prompts=False):
        from core.tasks.download_depots_task import DownloadDepotsTask
        original = DownloadDepotsTask._prepare_downloads
        commands_seen = []
        def prepare(task, data, selected, destination):
            commands, skipped, sizes = original(task, data, selected, destination)
            commands_seen.extend(commands)
            target = Path(destination)/'steamapps/common/Example'
            code = 'from pathlib import Path; p=Path('+repr(str(target))+');p.mkdir(parents=True,exist_ok=True);(p/"example.sh").write_text("#!/bin/sh\\nexit 0\\n");print("100%");raise SystemExit('+str(7 if fail else 0)+')'
            return [[sys.executable, '-c', code]], skipped, sizes
        args = {'zip_path': str(self.archive), 'appid': 123}
        if not prompts:
            args.update(depots=['124'], dlcs=['125'], library=str(self.library))
        with patch.object(DownloadDepotsTask, '_prepare_downloads', prepare):
            result = self.engine.run_download(args)
        self.assertIn('-manifestfile', commands_seen[0])
        self.assertIn('-validate', commands_seen[0])
        return result

    def test_inspect_is_read_only_and_redacts_secrets(self):
        data = self.engine.run_action('inspect', {'zip_path': str(self.archive), 'appid': 123})
        self.assertEqual(data['appid'], '123')
        self.assertEqual(data['manifests']['124'], '999')
        self.assertNotIn('key', data['depots']['124'])
        self.assertNotIn('app_token', data)
        self.assertFalse(self.config.exists())

    def test_download_finalizes_acf_dlc_token_and_marker(self):
        result = self.download()
        acf = self.library/'steamapps/appmanifest_123.acf'
        self.assertTrue(acf.exists())
        self.assertIn('999', acf.read_text())
        config = self.config.read_text()
        self.assertEqual(config.count('AdditionalApps:'), 1)
        self.assertIn('123456789', config)
        self.assertIn('125:', config)
        self.assertTrue((Path(result['install_path'])/'.ACCELA/wired.json').exists())
        self.assertTrue((Path(result['install_path'])/'example.sh').stat().st_mode & 0o100)

    def test_failed_downloader_never_marks_installed(self):
        with self.assertRaisesRegex(RuntimeError, 'DepotDownloader failed'):
            self.download(fail=True)
        self.assertFalse((self.library/'steamapps/appmanifest_123.acf').exists())
        self.assertFalse(self.config.exists())
        self.assertTrue((self.library/'steamapps/common/Example/example.sh').exists())

    def test_selections_are_supplied_by_plugin(self):
        with patch.object(worker, 'prompt', side_effect=[['124'], ['125'], str(self.library)]) as selection:
            self.download(prompts=True)
        self.assertEqual([call.args[0] for call in selection.call_args_list], ['depots', 'dlcs', 'library'])

    def test_rejects_wrong_appid_and_unknown_depot(self):
        with self.assertRaisesRegex(ValueError, 'AppID'):
            self.engine.inspect(self.archive, 777)
        with self.assertRaisesRegex(ValueError, 'depot'):
            self.engine.run_download({'zip_path': str(self.archive), 'appid': 123, 'depots': ['555'], 'dlcs': [], 'library': str(self.library)})

    def test_rejects_install_path_traversal(self):
        with self.assertRaisesRegex(ValueError, 'Insecure'):
            worker.validate_game({'appid': '123', 'installdir': '../../outside'})

    def test_library_scan_and_confirmed_uninstall_stay_in_test_directory(self):
        self.download()
        games = self.engine.run_action('library', {})
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['appid'], '123')
        self.assertTrue(games[0]['is_accela_install'])
        with patch.object(worker, 'prompt', return_value=False):
            with self.assertRaises(InterruptedError):
                self.engine.run_action('uninstall', {'appid': 123})
        self.assertTrue((self.library/'steamapps/common/Example').exists())
        with patch.object(worker, 'prompt', return_value=True):
            self.engine.run_action('uninstall', {'appid': 123})
        self.assertFalse((self.library/'steamapps/common/Example').exists())
        self.assertFalse((self.library/'steamapps/appmanifest_123.acf').exists())

    def test_sls_config_actions_and_secret_redaction(self):
        self.config.write_text('API: yes\nAdditionalApps:\n', encoding='utf-8')
        self.engine.run_action('sls_token', {'appid': 123, 'token': '123456789'})
        self.engine.run_action('sls_fake', {'appid': 123, 'fake_appid': 480, 'name': 'Example'})
        value = self.engine.run_action('sls_status', {})
        self.assertEqual(value['app_tokens']['123'], '[configured]')
        self.assertIn('123', value['fake_appids'])
        self.engine.run_action('sls_fake_remove', {'appid': 123})
        self.assertNotIn('123', self.engine.run_action('sls_status', {})['fake_appids'])

    def test_uses_qcore_not_gui_application(self):
        self.assertEqual(type(self.engine.app).__name__, 'QCoreApplication')
        from PyQt6.QtWidgets import QApplication
        self.assertNotIsInstance(self.engine.app, QApplication)


if __name__ == '__main__':
    unittest.main(verbosity=2)
