# Tests

Run standard-library tests with `python3 -m unittest discover -s tests -v`. Runtime-specific cases skip when Millennium's Lua VM, `msgpack` or a prepared ACCELA runtime is unavailable. Tests use private temporary directories and mocked network responses.

`node tests/i18n-smoke.mjs` checks locale behavior without browser dependencies. The Chromium UI tests need Chromium and React 18 UMD fixtures:

```bash
npm install --prefix /tmp/wired-ui-deps react@18.3.1 react-dom@18.3.1
python3 tools/build.py
node tests/ui-smoke.mjs
node tests/store-ui-smoke.mjs
```

Set `CHROMIUM` if your browser executable has a different name. Native UI tests emulate the Steam SDK in offline Chromium; they do not launch Steam or authenticate accounts.
