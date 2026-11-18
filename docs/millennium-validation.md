# Millennium validation

Wired uses a Lua backend and built frontends at `.millennium/Dist/index.js` and `.millennium/Dist/webkit.js`. The Lua host launches a separate system-Python service over a private Unix socket. It does not depend on Python backend support in Millennium itself.

The integration test uses the installed Millennium Lua VM when available. It verifies startup, `millennium.ready()`, configuration persistence, status serialization, method validation, native diagnostic forwarding and service shutdown. Optional engine tests use the prepared ACCELA runtime without network access.

Chromium tests verify native-control integration, store action placement, theme gaps, long titles, DLC community links, late Proton badges, Denuvo visibility, automatic settings persistence, login initiation, fix eligibility and cloud draft behavior. Test fixtures simulate the SDK; they are not a substitute for checking every live Steam update and theme.

No package-owned Millennium library or personal startup repair is distributed in this repository. Steam must be restarted after updating a backend.

## Wired Logs tab

Open **Steam → Settings → Millennium → Wired → Logs** to view a unified, searchable feed.
The panel reads the local Millennium log directories (XDG state and legacy data locations),
CloudRedirect's `cloud_redirect.log` and `cr_debug.log`, SLSsteam log files,
Steam's cloud log, Wired IPC service logs, updater logs, RPC failures, and job diagnostics.

- Refresh manually or every 3 seconds; filter by severity, source, and text.
- Expand *Detected log files and runtime* to inspect available sources and their paths.
- *Copy filtered logs* copies the currently loaded, filtered, credential-redacted entries.
- The service retains up to 2,500 recent entries and transfers up to 600 at once, capped
  at 750 KiB per response; it reads at most 128 KiB from each selected file per poll.
  Original source files remain untouched and may contain additional historical details.
- Logs and tracebacks are redacted before being sent to the frontend. However, paths,
  account names and other non-secret context may still appear: inspect diagnostic text
  before sharing it publicly.
- The panel reports logged failures but does not independently guarantee that the
  CloudRedirect native hook has loaded or successfully synchronized a save.

The logging tests cover incremental ingestion, rotation, source filtering, symlink
exclusion, sensitive-field redaction, and the native frontend's error display.
