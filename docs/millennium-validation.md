# Millennium validation

Wired uses a Lua backend and built frontends at `.millennium/Dist/index.js` and `.millennium/Dist/webkit.js`. The Lua host launches a separate system-Python service over a private Unix socket. It does not depend on Python backend support in Millennium itself.

The integration test uses the installed Millennium Lua VM when available. It verifies startup, `millennium.ready()`, configuration persistence, status serialization, method validation, native diagnostic forwarding and service shutdown. Optional engine tests use the prepared ACCELA runtime without network access.

Chromium tests verify native-control integration, store action placement, theme gaps, long titles, DLC community links, late Proton badges, Denuvo visibility, automatic settings persistence, login initiation, fix eligibility and cloud draft behavior. Test fixtures simulate the SDK; they are not a substitute for checking every live Steam update and theme.

No package-owned Millennium library or personal startup repair is distributed in this repository. Steam must be restarted after updating a backend.
