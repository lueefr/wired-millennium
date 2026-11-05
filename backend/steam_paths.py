"""Resolve installations from Steam's own VDF/ACF records."""
from pathlib import Path
import re
from moon import steam_root, app_id


def vdf(text):
    tokens=re.findall(r'"(?:\\.|[^"\\])*"|[{}]|//[^\n]*',text)
    tokens=iter(token for token in tokens if not token.startswith('//'))
    def block(nested=False):
        result={}
        for key in tokens:
            if key=='}':
                if not nested:raise ValueError("Invalid VDF")
                return result
            if not key.startswith('"'):raise ValueError("Invalid VDF")
            key=re.sub(r'\\(["\\])',r'\1',key[1:-1]).lower()
            value=next(tokens,None)
            if value=='{':result[key]=block(True)
            elif value and value.startswith('"'):result[key]=re.sub(r'\\(["\\])',r'\1',value[1:-1])
            else:raise ValueError('Incomplete VDF')
        if nested:raise ValueError('Incomplete VDF')
        return result
    return block()


def installed_game(appid, require_installed=False):
    appid=app_id(appid);root=steam_root();libraries=[root]
    config=root/'steamapps/libraryfolders.vdf'
    if config.exists():
        for item in vdf(config.read_text()).get('libraryfolders',{}).values():
            if isinstance(item,dict) and item.get('path'):libraries.append(Path(item['path']))
    for library in libraries:
        manifest=library/'steamapps'/f'appmanifest_{appid}.acf'
        if not manifest.exists():continue
        state=vdf(manifest.read_text()).get('appstate',{})
        if str(state.get('appid'))!=appid:continue
        if require_installed and not int(state.get('stateflags','0')) & 4:continue
        folder=state.get('installdir','');common=(library/'steamapps/common').resolve()
        target=(common/folder).resolve()
        if not folder or target==common or not target.is_relative_to(common) or not target.is_dir():
            raise ValueError("Invalid game folder in Steam registry")
        return target
    raise RuntimeError("Game not installed. Install it before applying a fix.")
