# CloudRedirect integration

Wired follows the [Lumen CloudRedirect contract](https://github.com/swwayps/lumen) recorded in [provenance](lumen-provenance.json). The native hook and CLI come from the [official CloudRedirect upstream](https://github.com/crghofficial/cloudredirect). The installer verifies the published release SHA-256 digests and the ELF class against 64-bit Steam. If upstream still publishes 32-bit Linux assets, the installer builds the exact upstream release commit with CMake and `LINUX_32BIT=OFF`; it never loads a 32-bit library into steamrt64. A local C++20 toolchain and CMake are required for the fallback.

Configuration is stored under `~/.config/CloudRedirect`. Supported providers are local, synced folder, Google Drive, OneDrive, Cloudflare R2 and S3-compatible storage. Unknown configuration keys are preserved. Credentials and staged OAuth tokens are private files, never frontend return values.

OAuth uses PKCE and state validation, localhost callbacks and cancellable polling. Connection drafts are committed only by Save and restart. Switching remote providers offers migration or switching without migration. CLI failures trigger rollback of configuration and token snapshots; the migration source is preserved.

The achievement/playtime control writes `stats_sync_enabled`, `sync_achievements` and `sync_playtime` together. The native hook performs synchronization; this is separate from ACCELA's optional Goldberg achievement generation.

Provider authentication/probing and remote inventories use CloudRedirect's CLI. Saved-game inventories are paginated separately from connection settings. Real cloud authentication, remote migrations and achievement synchronization require user accounts and have not been validated by the offline suite.

The restart helper is fetched from the pinned Lumen commit and verified by SHA-256 during installation. Its upstream behavior is preserved.
