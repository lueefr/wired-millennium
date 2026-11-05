import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from components import ROOT
from runtime import runtime_env


class RealRuntimeIntegration(unittest.TestCase):
    def test_real_accela_sources_offline(self):
        prepared = ROOT/'prepared.json'
        if not prepared.exists():
            self.skipTest('Run components.py prepare and components.py engine first')
        data = json.loads(prepared.read_text())
        artifact = data['components']['accela']
        marker = ROOT/'engines'/artifact['sha256'][artifact['asset']]/'engine.json'
        if not marker.exists():
            self.skipTest('Run components.py engine first')
        engine = json.loads(marker.read_text())
        result = subprocess.run([engine['python'], str(Path(__file__).with_name('engine_scenarios.py')), engine['source']], capture_output=True, text=True, timeout=90, env=runtime_env())
        self.assertEqual(result.returncode, 0, result.stdout[-5000:]+'\n'+result.stderr[-5000:])
        self.assertIn('Ran 9 tests', result.stderr)


if __name__ == '__main__':
    unittest.main()
