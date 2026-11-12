#!/usr/bin/env bash
# Remove Wired and its managed library entries; keep shared dependencies and saves.
# Inspired by the one-command LuaTools Moon uninstaller workflow.
set -euo pipefail
PURGE=0
DRY_RUN=0
for argument in "$@"; do
  case "$argument" in
    --purge) PURGE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --help) printf '%s\n' 'Usage: uninstall.sh [--purge] [--dry-run]' 'Keeps Steam, Millennium, SLSsteam, CloudRedirect, games and saves.' '--purge also deletes Wired settings, sign-in tokens, cache and plugin backups.'; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$argument" >&2; exit 2 ;;
  esac
done
[[ ${EUID} -ne 0 ]] || { printf '%s\n' 'Run as your normal user.' >&2; exit 1; }
if ! ((DRY_RUN)); then
  if pgrep -x steam >/dev/null || pgrep -x steamwebhelper >/dev/null; then printf '%s\n' 'Close Steam before uninstalling.' >&2; exit 1; fi
fi
DATA_DIRECTORY="${XDG_DATA_HOME:-$HOME/.local/share}"
PLUGIN_DIRECTORY="$DATA_DIRECTORY/millennium/plugins/wired-millennium"
if ((DRY_RUN)); then printf '[plan] Remove Wired at %s; remove unchanged managed library scripts; purge=%s\n' "$PLUGIN_DIRECTORY" "$PURGE"; exit 0; fi
python3 - "$PLUGIN_DIRECTORY" "$DATA_DIRECTORY/wired-millennium" "$PURGE" <<'PY'
import json,os,shutil,sys
from pathlib import Path
plugin,data=map(Path,sys.argv[1:3]);purge=sys.argv[3]=='1'
if plugin.is_symlink() or data.is_symlink():raise SystemExit('Refusing to remove a symlinked installation or data directory.')
if plugin.exists():
    if json.loads((plugin/'plugin.json').read_text()).get('name')!='wired-millennium':raise SystemExit('The destination does not belong to Wired.')
    sys.path.insert(0,str(plugin/'backend'))
    if (plugin/'backend/updates.py').exists():
        from updates import cancel_pending
        cancel_pending()
    if (plugin/'backend/update_timer.py').exists():
        from update_timer import remove as remove_update_timer
        remove_update_timer()
    from moon import remove_integration
    for receipt in sorted((data/'apps').glob('*.json')):
        try:remove_integration(receipt.stem)
        except Exception as error:raise SystemExit('Library entry could not be removed safely: '+receipt.stem+'; '+str(error))
    shutil.rmtree(plugin)
if purge and data.exists():shutil.rmtree(data)
print('Wired uninstalled. Shared components, game files and saves were preserved.')
PY
