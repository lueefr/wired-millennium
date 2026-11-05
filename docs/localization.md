# Localization

`locales/en.json` is the English source catalog; each other catalog uses the same keys. `languages.json` maps Steam API names to locale identifiers. Catalogs are bundled into both frontends at build time. No network translation occurs when the plugin runs.

The native frontend waits for `SteamClient.Settings.GetCurrentLanguage()` before rendering. Store integration uses Steam's native setting when exposed, then the persisted client language read by the backend, then the store language parameter, Steam_Language cookie and HTML language. Unsupported values fall back to English. The Arabic catalog uses RTL direction inside Wired's settings without changing Steam's document direction.

The native element factory translates labels, descriptions, button children, modal text and accessibility labels. Editable values, URLs, AppIDs, game titles, provider identities and protocol arguments are not translated. Store presentation sinks use the same catalog. Native diagnostics remain English for consistent support reports.

Initial translations were machine-assisted. English and Brazilian Portuguese are primary maintenance languages; all other catalogs need native-speaker review. European Portuguese and Latin American Spanish are separate catalogs, even where wording is shared. The Steam language list comes from [Valve's documentation](https://partner.steamgames.com/doc/store/localization/languages).

When adding text, add the English key to all catalogs and preserve interpolation placeholders. `tests/test_localization.py` checks key coverage, language mappings, valid JSON and placeholders. `tests/i18n-smoke.mjs` checks Steam language precedence, fallback and RTL behavior.

Browser sign-in callback messages use the same offline catalogs and persisted Steam language. The installer includes the catalogs alongside both compiled frontends.
