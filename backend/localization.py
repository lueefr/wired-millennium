"""Steam language detection and offline text for browser sign-in callbacks."""
import json
from pathlib import Path
from functools import lru_cache

CATALOGS=Path(__file__).resolve().parents[1]/'locales'


def steam_language():
    from steam_paths import vdf
    for path in (Path.home()/'.steam/registry.vdf',Path.home()/'.local/share/Steam/registry.vdf'):
        if not path.is_file():
            continue
        try:
            value=vdf(path.read_text())
            for key in ('registry','hkcu','software','valve','steam'):
                value=value.get(key,{})
            language=value.get('language')
            if isinstance(language,str) and language:
                return language
        except (OSError,ValueError,AttributeError):
            continue
    return None


@lru_cache(maxsize=32)
def catalog(language):
    try:
        languages=json.loads((CATALOGS/'languages.json').read_text())
        locale=languages.get(language,'en')
        return json.loads((CATALOGS/(locale+'.json')).read_text())
    except (OSError,ValueError):
        return {}


def t(text):
    return catalog(steam_language()).get(text,text)
