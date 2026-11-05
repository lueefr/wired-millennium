"""Private JSON-lines worker. QCoreApplication only: no ACCELA window/terminal.

Run with ACCELA's bundled Python; upstream sources remain in the local cache.
The plugin owns orchestration, user decisions, progress, validation and failures.
"""
import contextlib
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import types
import uuid

PROTOCOL = sys.stdout


def event(kind, **values):
    PROTOCOL.write(json.dumps({'event': kind, **values}, default=str)+'\n')
    PROTOCOL.flush()


def prompt(kind, title, choices=None, multiple=False, default=None):
    identity = uuid.uuid4().hex
    event('prompt', id=identity, kind=kind, title=title, choices=choices or [], multiple=multiple, default=default)
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("Plugin channel closed during selection")
    response = json.loads(line)
    if response.get('id') != identity:
        raise ValueError("Outdated selection answer")
    if response.get('cancel'):
        raise InterruptedError("Operation canceled")
    return response.get('answer')


DEFAULTS = {'slssteam_mode': True, 'sls_config_management': True, 'library_mode': True, 'max_downloads': 16, 'use_steamless': False, 'auto_apply_goldberg': False, 'generate_achievements': False, 'create_application_shortcuts': False, 'fake_appid_for_online': '480'}


class Settings:
    def __init__(self, values):
        self.values = {**DEFAULTS, **values}

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is bool:
            return value.lower() in ('true', '1', 'yes') if isinstance(value, str) else bool(value)
        return type(value) if type is not None and value is not None else value

    def setValue(self, key, value):
        self.values[key] = value

    def contains(self, key):
        return key in self.values

    def sync(self):
        pass


class LogHandler(logging.Handler):
    def __init__(self, secrets):
        super().__init__()
        self.secrets = [str(x) for x in secrets if x]
        self.errors = []

    def emit(self, record):
        message = record.getMessage()
        # Upstream can include depot keys or bearer strings in logs.
        for secret in self.secrets:
            message = message.replace(secret, '[redacted]')
        message = re.sub(r'(?i)(Bearer\s+)\S+', r'\1[redacted]', message)
        message = re.sub(r'(?i)((?:token|api_key|depotkey)\s*[:=]\s*)\S+', r'\1[redacted]', message)
        event('log', level=record.levelname.lower(), message=message[:2000])
        if record.levelno >= logging.ERROR:
            self.errors.append(message[:2000])


def positive_id(value):
    text = str(value)
    if not text.isdigit() or not 0 < int(text) < 2**64:
        raise ValueError("Invalid numeric identifier")
    return text


def game_path(value):
    path = Path(value).expanduser().resolve()
    if not path.is_dir() or path == Path.home() or path == Path('/'):
        raise ValueError("Invalid game directory")
    return path


def validate_game(data, expected_appid=None):
    data['appid'] = positive_id(data.get('appid'))
    if expected_appid is not None and data['appid'] != positive_id(expected_appid):
        raise ValueError("Package AppID does not match requested")
    data['game_name'] = re.sub(r'[\x00-\x1f]', ' ', str(data.get('game_name') or 'App_'+data['appid'])).replace(chr(34), chr(39))
    folder = data.get('installdir')
    if folder and (Path(folder).name != folder or folder in ('.', '..') or '\\' in folder or any(ord(c) < 32 for c in folder) or chr(34) in folder):
        raise ValueError("Insecure installation folder received in package")
    for category in ('depots', 'manifests', 'dlcs'):
        for value in data.get(category, {}):
            positive_id(value)
    for manifest in data.get('manifests', {}).values():
        positive_id(manifest)
    return data


def safe_game(data):
    # No depot keys or application tokens cross into the frontend.
    return {key: value for key, value in data.items() if key not in ('depots', 'app_token')} | {'depots': {key: {k: v for k, v in info.items() if k != 'key'} for key, info in data.get('depots', {}).items()}}


class Engine:
    def __init__(self, source, config, state_dir):
        sys.path.insert(0, str(source))
        from PyQt6.QtCore import QCoreApplication
        self.app = QCoreApplication.instance() or QCoreApplication(['wired-engine'])
        # Replace settings before loading any tasks that import get_settings.
        self.settings = Settings(config)
        import utils.settings
        utils.settings.get_settings = lambda: self.settings
        from utils.paths import Paths
        Paths.BASE_DIR = Path(source)
        Paths.RES = Path(source)/'res'
        Paths.DEPS = Path(source)/'deps'
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Mutable library/version metadata belongs to plugin data, not source code.
        import utils.helpers
        utils.helpers.get_base_path = lambda: str(self.state_dir)
        from PyQt6 import QtWidgets
        def blocked(*args, **kwargs):
            raise RuntimeError("Routine tried to open Qt dialog; use plugin selection")
        for name in ('information', 'warning', 'critical', 'question'):
            setattr(QtWidgets.QMessageBox, name, blocked)
        for name in ('getOpenFileName', 'getOpenFileNames', 'getSaveFileName', 'getExistingDirectory'):
            setattr(QtWidgets.QFileDialog, name, blocked)
        from core import morrenus_api
        import requests
        morrenus_api._session.close()
        morrenus_api._session = requests.Session()  # Keep normal CA/hostname verification.
        # Auxiliary tools cannot consume the plugin's JSON input channel.
        original_popen = subprocess.Popen
        class ToolProcess(original_popen):
            def __init__(self, *args, **kwargs):
                kwargs.setdefault('stdin', subprocess.DEVNULL)
                super().__init__(*args, **kwargs)
        subprocess.Popen = ToolProcess
        self.config = config
        self.handler = LogHandler([v for k, v in config.items() if 'key' in k or 'token' in k or 'cookie' in k])
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(self.handler)
        root.setLevel(logging.INFO)

    def wire(self, task):
        if hasattr(task, 'progress'):
            task.progress.connect(lambda *args: event('progress', message=' '.join(map(str, args))))
        if hasattr(task, 'progress_percentage'):
            task.progress_percentage.connect(lambda value: event('progress', percent=value))
        return task

    def inspect(self, archive, appid=None):
        from core.tasks.process_zip_task import ProcessZipTask
        # Parsing/preview must not mutate the running Steam/SLSsteam configuration.
        original = ProcessZipTask._extract_app_token
        def token(content, app_id):
            match = re.search(r'addtoken\s*\(\s*'+re.escape(str(app_id))+r'\s*,\s*"([^"\r\n]+)"\s*\)', content, re.I)
            return match.group(1) if match else None
        ProcessZipTask._extract_app_token = staticmethod(token)
        try:
            data = ProcessZipTask().run(str(archive))
        finally:
            ProcessZipTask._extract_app_token = staticmethod(original)
        validate_game(data, appid)
        self.handler.secrets.extend([data.get('app_token')] if data.get('app_token') else [])
        self.handler.secrets.extend(info['key'] for info in data.get('depots', {}).values() if info.get('key'))
        return data

    def task_manager(self):
        from managers.task_manager import TaskManager
        from PyQt6.QtCore import QObject
        manager = TaskManager.__new__(TaskManager)
        QObject.__init__(manager)
        manager.settings = self.settings
        manager.main_window = None
        return manager

    def libraries(self):
        from core.steam_helpers import get_steam_libraries
        return list(get_steam_libraries())

    def scan(self):
        from managers.game_manager import GameManager
        from core.steam_helpers import find_steam_install
        manager = GameManager(types.SimpleNamespace(settings=self.settings))
        for library in self.libraries():
            manager._scan_library(library, find_steam_install())
        return manager, manager.get_all_games()

    def run_download(self, args):
        from core.tasks.download_depots_task import DownloadDepotsTask
        from utils.helpers import ensure_dotnet_availability
        from utils.steam_manifest import get_game_directory
        if not args.get('zip_path'):
            from core.morrenus_api import download_manifest
            archive, error = download_manifest(positive_id(args['appid']))
            if error or not archive:
                raise RuntimeError(error or "Failed to get manifest")
            from archive_utils import validate_archive
            validate_archive(Path(archive))
            args['zip_path'] = archive
        data = self.inspect(args['zip_path'], args.get('appid'))
        event('metadata',appid=data['appid'],name=data.get('game_name',''))
        if not data.get('depots'):
            raise RuntimeError("The package does not contain depots to download")
        choices = [{'value': key, 'label': info.get('desc', key), 'size': info.get('size'), 'os': info.get('oslist'), 'language': info.get('language')} for key, info in data['depots'].items()]
        selected = args.get('depots')
        if selected is None:
            selected = prompt('depots', data.get('game_name', 'Select depots'), choices, multiple=True)
        if not isinstance(selected, list) or not selected or not set(selected).issubset(data['depots']):
            raise ValueError("Invalid depot selection")
        if not all(key in data.get('manifests', {}) for key in selected):
            raise ValueError('A manifest is missing for a selected depot')
        selected_dlcs = args.get('dlcs')
        if data.get('dlcs') and selected_dlcs is None:
            selected_dlcs = prompt('dlcs', 'DLCs', [{'value': key, 'label': name} for key, name in data['dlcs'].items()], multiple=True, default=[])
        if selected_dlcs is not None:
            if not isinstance(selected_dlcs, list) or not set(selected_dlcs).issubset(data.get('dlcs', {})):
                raise ValueError("Invalid DLC selection")
            data['dlcs'] = {key: data['dlcs'][key] for key in selected_dlcs}
            data['selected_dlcs'] = selected_dlcs
        destination = args.get('library')
        libraries = self.libraries() if destination is None else []
        if destination is None:
            destination = prompt('library', 'Steam library', [{'value': value, 'label': value} for value in libraries]) if libraries else prompt('path', "Target library folder")
        if not isinstance(destination, str) or not Path(destination).is_absolute():
            raise ValueError('Choose a library using an absolute path')
        dest = Path(destination).resolve()
        if not (dest/'steamapps').is_dir():
            raise ValueError("The library must contain the steamapps folder")
        data['selected_depots_list'] = selected
        game_directory = Path(get_game_directory(str(dest), data)).resolve()
        if not game_directory.is_relative_to((dest/'steamapps/common').resolve()):
            raise ValueError("Destination outside the library")
        if not ensure_dotnet_availability():
            raise RuntimeError("Unable to prepare .NET 9")
        task = self.wire(DownloadDepotsTask())
        commands, skipped, sizes = task._prepare_downloads(data, selected, str(dest))
        if skipped or len(commands) != len(selected):
            raise RuntimeError("Unable to prepare all selected depots")
        task.total_download_size_for_this_job = sum(sizes)
        event('progress',phase='content',bytes=0,total=sum(sizes),percent=0)
        for index, command in enumerate(commands):
            event('progress', message=f'Depot {selected[index]} ({index+1}/{len(commands)})', percent=100*sum(sizes[:index])/sum(sizes) if sum(sizes)>0 else 100*index/max(1,len(commands)))
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
            # Children inherit our process group, so plugin pause/cancel covers the tree.
            for line in process.stdout:
                text = line.strip()
                if text:
                    event('progress', message=text[:1000])
                    match = re.search(r'(\d+(?:\.\d+)?)%', text)
                    if match:
                        fraction=min(100,float(match.group(1)))/100
                        event('progress',percent=100*(sum(sizes[:index])+sizes[index]*fraction)/sum(sizes) if sum(sizes)>0 else 100*(index+fraction)/max(1,len(commands)),bytes=int(sum(sizes[:index])+sizes[index]*fraction),total=sum(sizes),phase='content',bytes_estimated=True)
            if process.wait() != 0:
                raise RuntimeError(f'DepotDownloader failed on depot {selected[index]}; files kept to resume')
        event('progress', phase='finalizing', percent=100, bytes=sum(sizes), total=sum(sizes), message="Finishing installation")
        self.finalize(data, task, str(dest), game_directory)
        return {'game': safe_game(data), 'install_path': str(game_directory), 'message': "Download and finalization completed; restart Steam to update the library"}

    def finalize(self, data, task, destination, game_directory):
        from managers.cli_manager import CLITaskManager
        from utils.yaml_config_manager import get_user_config_path, backup_config_on_startup, add_app_token, ensure_slssteam_api_enabled
        logger = logging.getLogger('wired.finalize')
        self.handler.errors.clear()
        manager = CLITaskManager(self.settings, logger)
        manager.game_data = data
        manager.download_task = task
        manager.current_dest_path = destination
        manager.slssteam_mode_was_active = self.settings.value('slssteam_mode', True, type=bool)
        config = get_user_config_path()
        if manager.slssteam_mode_was_active:
            config.parent.mkdir(parents=True, exist_ok=True)
            if not config.exists():
                config.write_text('API: yes\nAdditionalApps:\n', encoding='utf-8')
            backup_config_on_startup(config)
            ensure_slssteam_api_enabled(config)
            if data.get('app_token') and not add_app_token(config, data['appid'], data['app_token']):
                raise RuntimeError("Failed to register token in SLSsteam configuration")
            from utils.yaml_config_manager import add_additional_app, add_dlc_data
            if not add_additional_app(config, data['appid'], data.get('game_name', '')):
                # Upstream returns False for an already-present entry too.
                logging.info("AppID already configured or configuration not modified")
            for dlc_id, name in data.get('dlcs', {}).items():
                add_dlc_data(config, data['appid'], dlc_id, name)
        else:
            manager._write_app_token(destination)
        manager._move_manifests_to_depotcache()
        manager._save_main_depot_info()
        self.task_manager()._run_chmod_recursive(str(game_directory))
        if self.settings.value('auto_apply_goldberg', False, type=bool):
            self.run_action('goldberg_apply', {'path': str(game_directory), 'appid': data['appid'], 'name': data.get('game_name', '')})
        if self.settings.value('use_steamless', False, type=bool):
            self.run_action('steamless', {'path': str(game_directory)})
        if self.settings.value('generate_achievements', False, type=bool):
            self.run_action('achievements', {'appid': data['appid']})
        if self.settings.value('create_application_shortcuts', False, type=bool):
            self.run_action('shortcuts', {'appid': data['appid'], 'name': data.get('game_name', '')})
        if self.handler.errors:
            raise RuntimeError("Incomplete completion:"+self.handler.errors[-1])
        # Only publish the installed manifest after successful download + post-processing.
        from utils.steam_manifest import build_acf_content, get_install_folder_name
        import tempfile
        target = Path(destination)/'steamapps'/f"appmanifest_{data['appid']}.acf"
        content = build_acf_content(data, task.total_download_size_for_this_job, get_install_folder_name(data), include_depots=True, log_proton=True, logger=logger)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, prefix='.wired-acf-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        marker = game_directory/'.ACCELA'
        marker.mkdir(exist_ok=True)
        (marker/'wired.json').write_text(json.dumps({'appid': data['appid'], 'selected_depots': data['selected_depots_list'], 'selected_dlcs': data.get('selected_dlcs', [])}), encoding='utf-8')

    def run_action(self, action, args):
        if action == 'health':
            from utils.helpers import get_dotnet_path
            return {'version': (Path(sys.path[0])/'res/version').read_text().strip(), 'qt_application': type(self.app).__name__, 'gui': False, 'libraries': self.libraries(), 'dotnet': get_dotnet_path(), 'actions': ACTIONS}
        if action == 'download':
            return self.run_download(args)
        if action == 'inspect':
            return safe_game(self.inspect(args['zip_path'], args.get('appid')))
        if action == 'library':
            return self.scan()[1]
        if action == 'check_updates':
            from core.tasks.manifest_check_task import ManifestCheckTask
            games = self.scan()[1]
            results = {}
            task = ManifestCheckTask(games)
            task.game_update_checked.connect(lambda appid, status: results.update({appid: status}))
            task.progress.connect(lambda done, total: event('progress', message=f'{done}/{total} games', percent=100*done/max(1,total)))
            task.run()
            return results
        if action in ('search', 'api_status'):
            from core import morrenus_api
            if action == 'search':
                return morrenus_api.search_games(str(args.get('query', ''))[:200], limit=50)
            return {'health': morrenus_api.check_health(), 'account': morrenus_api.get_user_stats()}
        if action == 'dependencies':
            from utils.helpers import ensure_dotnet_availability
            if not ensure_dotnet_availability():
                raise RuntimeError("Failed to prepare .NET 9")
            return {'dotnet': True}
        if action == 'chmod':
            return {'changed': self.task_manager()._run_chmod_recursive(str(game_path(args['path'])))}
        if action in ('goldberg_apply', 'goldberg_remove'):
            manager = self.task_manager()
            method = manager.apply_goldberg_to_game if action == 'goldberg_apply' else manager.remove_goldberg_from_game
            if not method(str(game_path(args['path'])), positive_id(args['appid']), str(args.get('name', '')), show_dialog=False):
                raise RuntimeError("No compatible/backup files found for Goldberg")
            if self.handler.errors:
                raise RuntimeError(self.handler.errors[-1])
            return {'success': True}
        if action == 'steamless':
            from core.tasks.steamless_task import SteamlessIntegration
            from utils.paths import Paths
            task = SteamlessIntegration(str(Paths.deps('Steamless')))
            task.progress.connect(lambda message: event('progress', message=message))
            errors = []
            task.error.connect(errors.append)
            result = task.process_game_with_steamless(str(game_path(args['path'])))
            if errors or not result:
                raise RuntimeError('; '.join(errors) or "Steamless did not complete")
            return {'result': result}
        if action == 'achievements':
            from core.tasks.generate_achievements_task import GenerateAchievementsTask
            task = self.wire(GenerateAchievementsTask())
            result = task.run(positive_id(args['appid']))
            if not result or not result.get('success'):
                raise RuntimeError((result or {}).get('message', "Failed to generate achievements"))
            return result
        if action == 'shortcuts':
            from core.tasks.application_shortcuts import ApplicationShortcutsTask
            task = self.wire(ApplicationShortcutsTask())
            task.set_api_key(self.settings.value('sgdb_api_key', ''))
            if not task.run(positive_id(args['appid']), str(args.get('name', ''))):
                raise RuntimeError("Failed to create shortcuts; check out the SteamGridDB key")
            return {'success': True}
        if action in ('sls_status', 'sls_token', 'sls_fake', 'sls_fake_remove', 'sls_repair'):
            from utils import yaml_config_manager as yaml
            config = yaml.get_user_config_path()
            if action == 'sls_status':
                return {'path': str(config), 'app_tokens': {key: '[configured]' for key in yaml.get_app_tokens(config)}, 'fake_appids': sorted(yaml.get_fake_app_ids(config))}
            yaml.backup_config_on_startup(config)
            if action == 'sls_token':
                success = yaml.add_app_token(config, positive_id(args['appid']), str(args['token']))
            elif action == 'sls_fake':
                success = yaml.add_fake_app_id(config, positive_id(args['appid']), str(args.get('name', '')), positive_id(args.get('fake_appid', '480')))
            elif action == 'sls_fake_remove':
                success = yaml.remove_fake_app_id(config, positive_id(args['appid']))
            else:
                repaired = yaml.fix_slssteam_config_indentation(config)
                enabled = yaml.ensure_slssteam_api_enabled(config)
                return {'indentation_changed': repaired, 'api_changed': enabled}
            if not success:
                raise RuntimeError("Configuration has not been modified; check out the SLSsteam archive")
            return {'success': True}
        if action == 'uninstall':
            appid = positive_id(args['appid'])
            manager, games = self.scan()
            candidates = [g for g in games if str(g.get('appid')) == appid]
            if args.get('path'):
                candidates = [g for g in candidates if Path(g['install_path']).resolve() == game_path(args['path'])]
            if len(candidates) != 1:
                raise ValueError("Missing or ambiguous installation; tell the path")
            game = candidates[0]
            resolved = Path(game['install_path']).resolve()
            common = (Path(game['library_path'])/'steamapps/common').resolve()
            if not resolved.is_relative_to(common) or resolved == common or Path(game['install_path']).is_symlink():
                raise ValueError("Uninstall target outside the library")
            if not game.get('is_accela_install'):
                raise ValueError("Plugin uninstallation limited to games managed by ACCELA/Wired")
            answer = prompt('confirm', "Remove Permanently"+str(game['install_path'])+'?', default=False)
            if answer is not True:
                raise InterruptedError("Uninstall canceled")
            success, error = manager.uninstall_game(game, remove_from_library=True, remove_shortcuts=bool(args.get('remove_shortcuts', False)))
            if not success:
                raise RuntimeError(error or "Failed to uninstall game")
            return {'success': True}
        raise ValueError("Unknown operation")


ACTIONS = ['health', 'download', 'inspect', 'library', 'check_updates', 'search', 'api_status', 'dependencies', 'chmod', 'goldberg_apply', 'goldberg_remove', 'steamless', 'achievements', 'shortcuts', 'sls_status', 'sls_token', 'sls_fake', 'sls_fake_remove', 'sls_repair', 'uninstall']


def main():
    request = json.loads(sys.stdin.readline())
    with contextlib.redirect_stdout(sys.stderr):
        engine = Engine(Path(request['source']), request.get('settings', {}), Path(request['state_dir']))
        args = request.get('args', {})
        if args.get('token'):
            engine.handler.secrets.append(str(args['token']))
        result = engine.run_action(request['action'], args)
        engine.app.processEvents()
    event('result', value=result)


if __name__ == '__main__':
    try:
        main()
    except InterruptedError as exc:
        event('cancelled', message=str(exc))
        sys.exit(2)
    except BaseException as exc:
        event('error', message=str(exc))
        sys.exit(1)
