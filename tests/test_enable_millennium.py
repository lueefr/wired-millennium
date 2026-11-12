import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('enable_millennium', ROOT/'tools/enable_millennium.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EnableMillenniumTests(unittest.TestCase):
    def test_enable_preserves_other_settings_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary)/'config.json'
            existing = {'plugins': {'enabledPlugins': ['extendium'], 'other': {'keep': True}}, 'general': {'injectCSS': False}}
            config.write_text(json.dumps(existing))
            self.assertTrue(module.enable(config))
            updated = json.loads(config.read_text())
            self.assertEqual(updated['plugins']['enabledPlugins'], ['extendium', 'wired-millennium'])
            self.assertEqual(updated['plugins']['other'], {'keep': True})
            self.assertEqual(updated['general'], {'injectCSS': False})
            self.assertFalse(module.enable(config))
            self.assertEqual(json.loads(config.read_text()), updated)
            self.assertEqual(json.loads((config.parent/'config.json.wired-backup').read_text()), existing)

    def test_invalid_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary)/'config.json'
            for content in ('broken json', '{"plugins": {"enabledPlugins": "incorrect"}}'):
                config.write_text(content)
                with self.assertRaises(RuntimeError):
                    module.enable(config)
                self.assertEqual(config.read_text(), content)

    def test_missing_or_linked_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary)/'config.json'
            with self.assertRaises(RuntimeError):
                module.enable(config)
            target = Path(temporary)/'target.json'
            target.write_text('{}')
            config.symlink_to(target)
            with self.assertRaises(RuntimeError):
                module.enable(config)
            self.assertEqual(target.read_text(), '{}')

    @unittest.skipIf(os.geteuid() == 0, 'Installer intentionally refuses root')
    def test_plugin_only_installer_stops_starts_enables_and_restarts(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            source = home/'source'
            source.mkdir()
            (source/'tools').mkdir()
            for name in ('install.sh', 'tools/enable_millennium.py'):
                file = source/name
                file.write_text((ROOT/name).read_text())
            (source/'plugin.json').write_text('{"name":"wired-millennium"}')
            (source/'install-plugin.py').write_text('from pathlib import Path\nprint("Wired staged")\n')
            steamroot = home/'.steam/steam'
            (steamroot/'steamapps').mkdir(parents=True)
            (steamroot/'config').mkdir()
            (home/'.steam-on').touch()
            fakebin = home/'bin'
            fakebin.mkdir()
            steam = fakebin/'steam'
            steam.write_text("""#!/bin/sh
if [ "${1:-}" = "-shutdown" ]; then
  printf 'stop\\n' >> "$HOME/steam-events"
  rm -f "$HOME/.steam-on"
else
  printf 'start\\n' >> "$HOME/steam-events"
  touch "$HOME/.steam-on"
  mkdir -p "$XDG_CONFIG_HOME/millennium"
  if [ ! -f "$XDG_CONFIG_HOME/millennium/config.json" ]; then
    printf '{"plugins":{"enabledPlugins":["other-plugin"]},"misc":{"keep":true}}\\n' > "$XDG_CONFIG_HOME/millennium/config.json"
  fi
fi
""")
            steam.chmod(0o755)
            sls = home/'.local/share/SLSsteam'
            wrapper = sls/'path/steam'
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text('#!/bin/sh\\nprintf "sls-wrapper\\\\n" >> "$HOME/steam-events"\\nexec "$HOME/bin/steam" "$@"\\n')
            wrapper.chmod(0o755)
            (sls/'SLSsteam.so').touch()
            (sls/'library-inject.so').touch()
            pgrep = fakebin/'pgrep'
            pgrep.write_text('#!/bin/sh\ntest -f "$HOME/.steam-on"\n')
            pgrep.chmod(0o755)
            release = home/'os-release'
            release.write_text('ID=arch\n')
            install = source/'install.sh'
            install.write_text(install.read_text().replace('/etc/os-release', str(release)))
            env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home/'settings'),
                       PATH=str(fakebin)+':'+os.environ['PATH'])
            result = subprocess.run(['bash', str(install), '--plugin-only'], env=env,
                                    capture_output=True, text=True, timeout=35)
            self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)
            self.assertEqual((home/'steam-events').read_text().splitlines(),
                             ['stop', 'sls-wrapper', 'start', 'stop', 'sls-wrapper', 'start'])
            settings = json.loads((home/'settings/millennium/config.json').read_text())
            self.assertEqual(settings['plugins']['enabledPlugins'], ['other-plugin', 'wired-millennium'])
            self.assertTrue((home/'.steam-on').exists())


if __name__ == '__main__':
    unittest.main()
