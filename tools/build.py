#!/usr/bin/env python3
"""Build the native Steam frontend and the store integration."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
output=root/'.millennium/Dist';output.mkdir(parents=True,exist_ok=True)
catalogs={path.stem:json.loads(path.read_text()) for path in (root/'locales').glob('*.json') if path.stem not in ('languages','source-pt-BR')}
languages=json.loads((root/'locales/languages.json').read_text())
localization='window.WIRED_LOCALES='+json.dumps(catalogs,ensure_ascii=False)+';\nwindow.WIRED_LANGUAGES='+json.dumps(languages)+';\n'+(root/'public/i18n.js').read_text()
shared=localization+'\n'+(root/'public/wired.js').read_text()
(output/'index.js').write_text(shared+'\n'+(root/'public/native.js').read_text())
(output/'webkit.js').write_text(shared+'\n'+(root/'public/webkit.js').read_text())
print("Native frontend and store integration compiled")
