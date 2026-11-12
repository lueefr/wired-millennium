#!/usr/bin/env bash
# Install native Millennium, SLSsteam Moon, CloudRedirect and Wired, in that order.
# Workflow inspired by swwayps/luatools-moon; independently implemented.
set -euo pipefail
REPOSITORY='lueefr/wired-millennium'
REF='main'
DRY_RUN=0
PLUGIN_ONLY=0
for argument in "$@"; do
  case "$argument" in
    --dry-run) DRY_RUN=1 ;;
    --plugin-only) PLUGIN_ONLY=1 ;;
    --help) printf '%s\n' 'Usage: install.sh [--dry-run] [--plugin-only]' 'Automatically closes Steam, installs Wired, starts Steam, enables Wired and restarts Steam.' '--plugin-only updates Wired without changing dependencies.'; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$argument" >&2; exit 2 ;;
  esac
done
say() { printf '[Wired] %s\n' "$*"; }
run() { if ((DRY_RUN)); then printf '[plan]'; printf ' %q' "$@"; printf '\n'; else "$@"; fi; }
die() { say "$*" >&2; exit 1; }
[[ ${EUID} -ne 0 ]] || die 'Run this installer as your normal user, without sudo.'
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || die 'Native Linux x86_64 Steam is required.'
# Shut down the client through Steam itself so it can flush its state before files change.
steam_running() {
  pgrep -u "$(id -u)" -x steam >/dev/null || pgrep -u "$(id -u)" -x steamwebhelper >/dev/null
}
stop_steam() {
  steam_running || return 0
  say 'Asking Steam to shut down gracefully...'
  "$STEAM_CMD" -shutdown >/dev/null 2>&1 || true
  for ((attempt=0; attempt<90; attempt++)); do
    steam_running || return 0
    sleep 1
  done
  die 'Steam did not close within 90 seconds. Close any running games and retry; no process was force-killed.'
}
start_steam() {
  say 'Starting Steam...'
  "$STEAM_CMD" >/dev/null 2>&1 </dev/null &
  disown || true
  for ((attempt=0; attempt<90; attempt++)); do
    if pgrep -u "$(id -u)" -x steam >/dev/null && pgrep -u "$(id -u)" -x steamwebhelper >/dev/null && [[ -f "$MILLENNIUM_CONFIG" ]]; then
      sleep 3
      if pgrep -u "$(id -u)" -x steam >/dev/null && pgrep -u "$(id -u)" -x steamwebhelper >/dev/null; then return 0; fi
    fi
    sleep 1
  done
  die 'Steam or the Millennium configuration did not become ready within 90 seconds.'
}
STEAM_CMD=''
MILLENNIUM_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/millennium/config.json"
if ! ((DRY_RUN)); then
  STEAM_CMD=$(command -v steam || true)
  [[ -n "$STEAM_CMD" ]] || die 'Native Steam launcher not found in PATH.'
  stop_steam
fi
# Never guess a Steam path inside a Flatpak/Snap container.
STEAM_ROOT=''
for candidate in "${HOME}/.steam/steam" "${HOME}/.local/share/Steam"; do
  if [[ -d $candidate/steamapps && -d $candidate/config ]]; then STEAM_ROOT=$candidate; break; fi
done
[[ -n $STEAM_ROOT || $DRY_RUN == 1 ]] || die 'Native Steam was not found. Flatpak and Snap are unsupported by Millennium.'
[[ -r /etc/os-release ]] || die 'Cannot identify this Linux distribution.'
# os-release is the system-owned distribution metadata file.
. /etc/os-release
DISTRIBUTION=" ${ID:-} ${ID_LIKE:-} "
say "Distribution: ${PRETTY_NAME:-${ID:-unknown}}"
if ! ((PLUGIN_ONLY)); then
  case "$DISTRIBUTION" in
    *' arch '*) run sudo pacman -S --needed curl python git tar unzip 7zip ;;
    *' debian '*|*' ubuntu '*) run sudo apt-get update; run sudo apt-get install -y curl python3 git tar unzip p7zip-full ;;
    *' fedora '*|*' rhel '*) run sudo dnf install -y curl python3 git tar unzip p7zip p7zip-plugins ;;
    *' suse '*|*' opensuse '*) run sudo zypper --non-interactive install curl python3 git tar unzip 7zip ;;
    *' nixos '*) command -v millennium >/dev/null || die 'Enable Millennium using its official NixOS flake first: https://docs.steambrew.app/users/getting-started/installation' ;;
    *) say 'Checking existing tools; install curl, Python 3, git, tar, unzip and 7z with your package manager if needed.' ;;
  esac
  if command -v millennium >/dev/null || [[ -f /usr/lib/millennium/libmillennium_x64.so || -f /usr/lib/millennium/libmillennium_x86.so || -f $STEAM_ROOT/ubuntu12_32/libmillennium_x86.so ]]; then
    say 'Millennium is already installed.'
  else
    case "$DISTRIBUTION" in
      *' arch '*)
        if command -v yay >/dev/null; then run yay -S --needed millennium
        elif command -v paru >/dev/null; then run paru -S --needed millennium
        else
          run sudo pacman -S --needed base-devel
          if ((DRY_RUN)); then say 'Build millennium from https://aur.archlinux.org/millennium.git with makepkg -si.'
          else
            AUR_DIRECTORY=$(mktemp -d); trap 'rm -rf -- "$AUR_DIRECTORY"' EXIT
            git clone https://aur.archlinux.org/millennium.git "$AUR_DIRECTORY/millennium"
            (cd "$AUR_DIRECTORY/millennium" && makepkg -si)
            rm -rf -- "$AUR_DIRECTORY"; trap - EXIT
          fi
        fi ;;
      *)
        if ((DRY_RUN)); then say 'Run the official installer: https://steambrew.app/install.sh'
        else
          MILLENNIUM_SCRIPT=$(mktemp)
          trap 'rm -f -- "$MILLENNIUM_SCRIPT"' EXIT
          curl --proto '=https' --tlsv1.2 -fsSL https://steambrew.app/install.sh -o "$MILLENNIUM_SCRIPT"
          bash "$MILLENNIUM_SCRIPT"
          rm -f -- "$MILLENNIUM_SCRIPT"; trap - EXIT
        fi ;;
    esac
  fi
fi
if ((DRY_RUN)); then say 'Install SLSsteam Moon, then CloudRedirect, then Wired from the main branch; shut down, start, enable and restart Steam automatically. No release is required.'; exit 0; fi
for tool in curl python3 git tar unzip; do command -v "$tool" >/dev/null || die "Missing required tool: $tool"; done
SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)
if [[ -f $SCRIPT_DIRECTORY/install-plugin.py && -f $SCRIPT_DIRECTORY/plugin.json ]]; then
  SOURCE_DIRECTORY=$SCRIPT_DIRECTORY
else
  CHECKOUT=$(mktemp -d); trap 'rm -rf -- "$CHECKOUT"' EXIT
  git clone --depth 1 --branch "$REF" "https://github.com/$REPOSITORY.git" "$CHECKOUT/source"
  SOURCE_DIRECTORY=$CHECKOUT/source
fi
OPTIONS=(--update)
((PLUGIN_ONLY)) && OPTIONS+=(--plugin-only)
python3 "$SOURCE_DIRECTORY/install-plugin.py" "${OPTIONS[@]}"
# First launch initializes Millennium's config on new installations.
say 'Installation complete. Initializing Millennium in Steam...'
start_steam
# Stop the client before editing its config: Millennium rewrites this file on shutdown.
stop_steam
python3 "$SOURCE_DIRECTORY/tools/enable_millennium.py" --config "$MILLENNIUM_CONFIG"
say 'Wired enabled. Restarting Steam...'
start_steam
say 'Steam is running with Wired enabled.'
