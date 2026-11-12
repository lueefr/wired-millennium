"""Millennium bridge: every ACCELA operation runs in the internal headless engine."""
import json
from pathlib import Path

from components import ROOT, write_json
from jobs import JobManager

CONFIG = ROOT/'settings.json'
DEFAULTS = {'providers': {'hubcap': True, 'lua_tools': True, 'sushi': True, 'ryuu': False}, 'api_list': [], 'accela_settings': {'slssteam_mode': True, 'sls_config_management': True, 'library_mode': True, 'max_downloads': 16, 'use_steamless': False, 'auto_apply_goldberg': False, 'generate_achievements': False, 'create_application_shortcuts': False, 'morrenus_api_key': '', 'sgdb_api_key': '', 'fake_appid_for_online': '480'}}


def settings():
    if CONFIG.exists():
        value = json.loads(CONFIG.read_text())
        return {**DEFAULTS, **value, 'accela_settings': {**DEFAULTS['accela_settings'], **value.get('accela_settings', {})}}
    return json.loads(json.dumps(DEFAULTS))


manager = JobManager(settings)


def GetSettings(**kwargs):
    return json.dumps(settings())


def SaveSettings(settings_json, **kwargs):
    data = json.loads(settings_json)
    if not isinstance(data, dict) or not isinstance(data.get('api_list'), list) or not isinstance(data.get('accela_settings', {}), dict):
        raise ValueError("Invalid configuration")
    for item in data['api_list']:
        if not isinstance(item, dict) or not isinstance(item.get('url'), str) or not item['url'].startswith('https://') or '<appid>' not in item['url']:
            raise ValueError('Each API needs an HTTPS URL containing <appid>')
        if not isinstance(item.get('api_key', ''), str):
            raise ValueError("Invalid API Key")
    providers = data.get('providers', {})
    if not isinstance(providers, dict) or any(type(value) is not bool for value in providers.values()):
        raise ValueError("Invalid provider options")
    engine_settings = data.get('accela_settings', {})
    key = engine_settings.get('morrenus_api_key', '')
    if not isinstance(key, str) or any(character in key for character in ('\r', '\n')):
        raise ValueError("Invalid Hubcap Key")
    if 'morrenus_api_key' in engine_settings:
        engine_settings['morrenus_api_key'] = key.strip()
    count = engine_settings.get('max_downloads', 16)
    if type(count) is not int or not 1 <= count <= 128:
        raise ValueError("Simultaneous downloads need to be between 1 and 128")
    # Launcher paths from v0.1 are no longer used; never fall back to the GUI.
    data.pop('accela_location', None)
    write_json(CONFIG, data)
    return json.dumps({'success': True})


def GetStatus(**kwargs):
    return json.dumps(manager.snapshot())


def StartDownload(appid, **kwargs):
    appid = int(appid)
    if not 0 < appid < 2**32:
        raise ValueError("Invalid AppID")
    return json.dumps(manager.enqueue('download', {'appid': appid}))


def StartTask(action, args_json='{}', **kwargs):
    args = json.loads(args_json)
    if not isinstance(args, dict):
        raise ValueError("Invalid arguments")
    return json.dumps(manager.enqueue(action, args))


def PrepareComponents(**kwargs):
    return json.dumps(manager.enqueue('prepare'))


def ReplyPrompt(job_id, prompt_id, answer_json='null', cancel=False, **kwargs):
    return json.dumps(manager.reply(job_id, prompt_id, json.loads(answer_json), cancel))


def Cancel(job_id=None, **kwargs):
    return json.dumps(manager.cancel(job_id))


def Pause(**kwargs):
    return json.dumps(manager.pause(True))


def Resume(**kwargs):
    return json.dumps(manager.pause(False))


def MoveJob(job_id, direction, **kwargs):
    return json.dumps(manager.move(job_id, direction))


def GetIntegrationState(appids_json='[]', **kwargs):
    from moon import status
    values=json.loads(appids_json)
    if not isinstance(values,list) or len(values)>100:raise ValueError("Invalid app list")
    return json.dumps(status(values))


def GetLuaToolsAuthStatus(**kwargs):
    from providers import status
    return json.dumps(status())


def StartLuaToolsLogin(**kwargs):
    from providers import begin_login
    return json.dumps(begin_login())


def CancelLuaToolsLogin(**kwargs):
    from providers import cancel
    return json.dumps(cancel())


def LogoutLuaTools(**kwargs):
    from providers import logout
    return json.dumps(logout())


def CloudStatus(**kwargs):
    import cloud
    return json.dumps(cloud.status())


def CloudAuthorize(provider, **kwargs):
    import cloud
    return json.dumps(cloud.authorize(provider))


def CloudAuthPoll(**kwargs):
    import cloud
    return json.dumps(cloud.auth_poll())


def CloudDiscard(**kwargs):
    import cloud
    return json.dumps(cloud.discard())


def GetLanguage(**kwargs):
    from localization import steam_language
    return json.dumps({'language':steam_language()})


_update_errors_seen = {}


def GetComponentUpdates(**kwargs):
    from updates import status
    from diagnostics import emit
    value=status()
    errors={**value.get('errors',{}),**{item['component']:item.get('error','Component update failed') for item in value['updates'] if item['decision']=='error'}}
    for component,message in errors.items():
        identity=(message,value.get('checked_at'))
        if _update_errors_seen.get(component)!=identity:
            emit(component+': '+message,'warning');_update_errors_seen[component]=identity
    return json.dumps(value)


def RespondToComponentUpdate(component,revision,decision,**kwargs):
    from updates import respond
    return json.dumps(respond(component,revision,decision))
