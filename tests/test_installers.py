import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_distribution_plans(self):
        cases=[('arch','', 'pacman'),('endeavouros','arch','pacman'),('ubuntu','debian','apt-get'),('fedora','','dnf'),('opensuse-tumbleweed','suse','zypper')]
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            for distro,related,expected in cases:
                release=base/'os-release';release.write_text(f'ID={distro}\nID_LIKE="{related}"\n')
                script=base/'install.sh';script.write_text((ROOT/'install.sh').read_text().replace('/etc/os-release',str(release)))
                result=subprocess.run(['bash',str(script),'--dry-run'],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn(expected,result.stdout)
                self.assertIn('SLSsteam Moon',result.stdout)
                self.assertIn('CloudRedirect',result.stdout)

    def test_uninstall_preserves_shared_components_and_data(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);data=home/'data';plugin=data/'millennium/plugins/wired-millennium'
            (plugin/'backend').mkdir(parents=True)
            (plugin/'plugin.json').write_text(json.dumps({'name':'wired-millennium'}))
            (plugin/'backend/moon.py').write_text('def remove_integration(appid): pass\n')
            own=data/'wired-millennium';own.mkdir();(own/'settings.json').write_text('{}')
            shared=data/'SLSsteam';shared.mkdir();(shared/'keep').write_text('shared')
            fakebin=home/'bin';fakebin.mkdir();pgrep=fakebin/'pgrep';pgrep.write_text('#!/bin/sh\nexit 1\n');pgrep.chmod(0o755)
            env=dict(os.environ,HOME=str(home),XDG_DATA_HOME=str(data),PATH=str(fakebin)+':'+os.environ['PATH'])
            result=subprocess.run(['bash',str(ROOT/'uninstall.sh')],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse(plugin.exists());self.assertTrue((own/'settings.json').exists());self.assertTrue((shared/'keep').exists())
            result=subprocess.run(['bash',str(ROOT/'uninstall.sh'),'--purge'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(own.exists());self.assertTrue(shared.exists())

    def test_uninstall_rejects_foreign_plugin(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp);plugin=data/'millennium/plugins/wired-millennium';plugin.mkdir(parents=True)
            (plugin/'plugin.json').write_text('{"name":"someone-else"}')
            fakebin=data/'bin';fakebin.mkdir();pgrep=fakebin/'pgrep';pgrep.write_text('#!/bin/sh\nexit 1\n');pgrep.chmod(0o755)
            env=dict(os.environ,XDG_DATA_HOME=str(data),PATH=str(fakebin)+':'+os.environ['PATH'])
            result=subprocess.run(['bash',str(ROOT/'uninstall.sh')],env=env,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertTrue(plugin.exists())
