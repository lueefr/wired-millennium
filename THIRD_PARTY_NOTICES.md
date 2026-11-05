# Third-party notices

Wired's original source is MIT licensed. This repository does not contain ACCELA, SLSsteam, CloudRedirect binaries or their extracted source trees; installers fetch upstream artifacts separately.

`backend/restart_steam.sh` is copied verbatim from `lua/restart_steam.sh` in [swwayps/lumen](https://github.com/swwayps/lumen), commit `52475c3ec0bbe2bf0ccdd209d86a40d99a9881fa`. Its exact file hash and behavior references are recorded in `docs/lumen-provenance.json`. Wired's MIT license does not relicense this third-party file. The installer retrieves this helper from the recorded upstream commit instead of bundling its contents in the repository.

The installation/uninstallation workflows and lua.tools protocols were studied from [LuaTools Moon](https://github.com/swwayps/luatools-moon); Wired's shell scripts and Python clients are independently implemented. Steam and Millennium interfaces remain subject to their respective projects' licenses.
