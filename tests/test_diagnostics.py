import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from diagnostics import emit, drain, redact


class DiagnosticsTests(unittest.TestCase):
    def test_credentials_are_redacted(self):
        message = 'smm_secret Bearer abc access_token=secret https://example.test/path?token=secret eyJabc.def.ghi'
        result = redact(message)
        for secret in ('smm_secret', 'Bearer abc', '=secret', 'example.test', 'eyJabc'):
            self.assertNotIn(secret, result)

    def test_bounded_drain_once(self):
        drain()
        for n in range(450):
            emit(str(n), 'warning')
        events = drain()
        self.assertEqual(len(events), 400)
        self.assertEqual(events[0]['message'], '50')
        self.assertEqual(events[-1]['level'], 'warning')
        self.assertEqual(drain(), [])
