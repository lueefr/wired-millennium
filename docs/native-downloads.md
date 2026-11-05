# Native download integration

Wired mounts a small React section inside Steam's Downloads view using Millennium's native SDK components. Download jobs expose phase, progress, byte counts, speed, prompts and pause/resume/cancel actions. Estimated metrics are prefixed with `≈`.

ACCELA jobs remain external worker jobs. Wired does not invent Steam internal scheduler entries, spoof installation state or overwrite unrelated download rows. Library actions use Steam's install wizard only after the user explicitly requests installation. Adding a package never starts an install.

Per-game actions mount in Steam's play bar; store actions are placed beside Community Hub. Controls inherit theme classes and spacing. Fixes require a managed/added integration and an actual installed ACF state plus a valid game directory.
