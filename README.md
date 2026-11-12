# Wired for Millennium

A native Steam plugin that adds library actions, an internal ACCELA download engine, lua.tools fixes, and CloudRedirect settings to [Millennium](https://github.com/SteamClientHomebrew/Millennium).

**Linux x86_64 · Native Steam · Lua backend · No separate ACCELA window**

[Install](#installation) · [Uninstall](#uninstalling) · [Languages](#languages) · [Development](#development) · [Report an issue](https://github.com/lueefr/wired-millennium/issues)

## Installation

Run the installer as your normal user:

```bash
curl -fsSL https://raw.githubusercontent.com/lueefr/wired-millennium/main/install.sh | bash
```

The installer asks Steam to shut down, installs or updates Wired, launches Steam once to initialize Millennium, then stops Steam, enables Wired in Millennium's configuration, and launches Steam again automatically. If SLSsteam Moon is installed, both launches use its native Steam wrapper (`~/.local/share/SLSsteam/path/steam`) to preserve the injection; an incomplete SLSsteam installation is reported instead of silently bypassed. It does not force-kill Steam; close any running games before installing. Other plugins and their settings are preserved. The previous Millennium configuration is backed up the first time Wired is enabled.

The installer detects your distribution, checks native Steam and Millennium, installs missing prerequisites, and installs **Millennium → SLSsteam Moon → CloudRedirect → Wired**. Existing Millennium installations are kept. Arch-based distributions use `yay`, `paru`, or the AUR build workflow; other supported distributions use Millennium's official installer. NixOS users must enable the [official flake](https://docs.steambrew.app/users/getting-started/installation) first.

Wired is enabled automatically. Settings live in Millennium's plugin configuration panel.

Inspect the plan without changing anything:

```bash
bash install.sh --dry-run
```

The repository's `main` branch is the install source. No Wired release is required. Run the same installation command to update; the existing plugin is backed up first. For an update that leaves dependencies alone:

```bash
curl -fsSL https://raw.githubusercontent.com/lueefr/wired-millennium/main/install.sh | bash -s -- --plugin-only
```

Flatpak, Snap, ARM, macOS and Windows installations are not supported by this installer. The [Millennium installation guide](https://docs.steambrew.app/users/getting-started/installation) describes its platform requirements.

## Using Wired

- **Add wire** adds the game's integration to the library without installing it. Install later using Steam's library controls.
- **Remove** removes only Wired's managed integration. Game files and saves stay in place.
- **Fixes** appears only for games that are both added and installed. Original files are backed up before applying a fix.
- A compact **Denuvo** badge appears only when Steam's official page provides that information.
- ACCELA tasks appear in Steam's Downloads page, with pause, resume and cancel controls. Estimated transfer figures are marked `≈`.

Controls inherit Steam's current theme. An external ACCELA job is displayed inside Downloads, rather than impersonating a download managed by Steam's internal scheduler.

## Settings

**Providers:** connect lua.tools, paste your Hubcap key, and enable individual manifest providers. Changes apply automatically; text fields use a short debounce and switches apply immediately. A status message confirms persistence or explains failures. Provider attempts follow the configured built-in order: Hubcap/Sadie → Luie → Sushi → Ryuu → custom sources. A provider returning an unavailable package does not prevent fallback.

**Downloads:** parallel transfers and optional Steamless/Goldberg processing. ACCELA is prepared on demand.

**Cloud:** choose a storage provider and manage achievement/playtime synchronization. Connection changes are staged because they may migrate data or restart Steam; **Save and restart** is the single explicit apply action. Advanced connection options are collapsed. Saved-game inventories are separate and paginated.

**Tools:** local package import, custom sources, and component maintenance. A custom source is validated and saved as one operation, rather than persisting an incomplete URL.

[Settings design and references](docs/settings-design.md)

## Languages

Wired automatically reads the Steam client's language using `SteamClient.Settings.GetCurrentLanguage()`. Store pages fall back to Steam's page setting, cookie or document language. The operating system's language does not override the Steam client. English is the fallback for unknown languages or messages.

Catalogs cover all 31 [Steam API language codes](https://partner.steamgames.com/doc/store/localization/languages), including English, Brazilian Portuguese, European Portuguese, Latin American Spanish, Simplified/Traditional Chinese and Arabic. Valve currently treats Arabic differently from selectable Steam UI languages; its catalog is included for compatible hosts.

Source code, documentation, diagnostics and catalog keys are English. Localized text lives under [`locales/`](locales). Initial non-English catalogs include machine translations and need native-speaker review; coverage checks do not establish translation quality. No translation service is called at runtime and no credentials are sent for translation.

[Localization architecture](docs/localization.md)

## Diagnostics and data

Open Millennium's logs and filter for Wired. Records include action, job ID, AppID, provider order, HTTP status/content type, byte counts, timings, validation failures and fallback results. API keys, bearer tokens and authenticated URLs are redacted. Response bodies are not logged.

Settings, session tokens, caches and receipts are stored under `${XDG_DATA_HOME:-~/.local/share}/wired-millennium`, with private permissions for credentials. These files and upstream binaries are not part of this repository. The Lua host uses a same-user Unix socket to reach the internal Python worker.

## Uninstalling

Close Steam, then run:

```bash
curl -fsSL https://raw.githubusercontent.com/lueefr/wired-millennium/main/uninstall.sh | bash
```

This removes Wired and its unchanged managed library scripts. It preserves Steam, Millennium, SLSsteam, CloudRedirect, game files and saves because these may be shared with other plugins. Modified scripts are preserved and reported instead of being silently deleted. To also remove Wired's settings, login tokens, cached runtime and plugin backups, add `--purge`:

```bash
curl -fsSL https://raw.githubusercontent.com/lueefr/wired-millennium/main/uninstall.sh | bash -s -- --purge
```

## Development

Python 3.10+ builds the plugin without Node dependencies:

```bash
python3 tools/build.py
python3 -m unittest discover -s tests -v
python3 install-plugin.py --update --plugin-only
```

Optional integration tests use a locally installed Millennium Lua host plus `msgpack`, the prepared ACCELA runtime, or headless Chromium. UI tests additionally need React's UMD test fixtures; see [tests/README.md](tests/README.md). Shell installers support `--dry-run` and are tested with mocked distributions and package managers. See [architecture](docs/accela-analysis.md) and [validation](docs/millennium-validation.md).

## Upstream projects

- [Millennium](https://github.com/SteamClientHomebrew/Millennium) — Steam plugin host and native UI SDK.
- [enter-the-wired / ACCELA](https://github.com/ciscosweater/enter-the-wired) — downloaded and prepared on demand.
- [SLSsteam Moon](https://github.com/swwayps/slsteam-moon) — separately installed dependency.
- [CloudRedirect Moon](https://github.com/swwayps/cloudredirect-moon) — native cloud hook and CLI.
- [LuaTools Moon](https://github.com/swwayps/luatools-moon) and [Lumen](https://github.com/swwayps/lumen) — integration, installer workflow, account and cloud behavior references.
- [Cyberia](https://github.com/rafaelcarpeta/cyberia) — original feature inspiration.

Wired's own code is [MIT licensed](LICENSE). Upstream components retain their own licenses and are downloaded from their respective projects. The copied Lumen Steam restart helper is separately identified in [provenance](docs/lumen-provenance.json); see [third-party notices](THIRD_PARTY_NOTICES.md).
