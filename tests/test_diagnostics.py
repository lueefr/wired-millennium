import sys
import os
import tempfile
from collections import deque
from unittest.mock import patch
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
import diagnostics
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


    def test_file_sources_incremental_rotation_and_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            source=directory/'cloud_redirect.log'
            source.write_text('[CR] loaded\nERROR Cloud upload failed: access_token="private-value"\n')
            secret=directory/'tokens.json';secret.write_text('private-json-data')
            linked=directory/'linked.log';linked.symlink_to(secret)
            with patch.object(diagnostics,'_roots',return_value=[('CloudRedirect',directory,'component')]), \
                 patch.object(diagnostics,'_cursors',{}), \
                 patch.object(diagnostics,'_events',deque(maxlen=2500)), \
                 patch.object(diagnostics,'_serial',0):
                first=diagnostics.snapshot(0,100)
                self.assertEqual(len(first['entries']),2)
                self.assertEqual(first['entries'][1]['level'],'error')
                self.assertEqual(first['entries'][1]['source'],'CloudRedirect / cloud_redirect.log')
                self.assertNotIn('private-value',str(first))
                self.assertNotIn('private-json-data',str(first))
                cursor=first['cursor']
                self.assertEqual(diagnostics.snapshot(cursor,100)['entries'],[])
                with source.open('a') as log:log.write('WARNING sync retry\n')
                second=diagnostics.snapshot(cursor,100)
                self.assertEqual(len(second['entries']),1)
                self.assertEqual(second['entries'][0]['level'],'warning')
                cursor=second['cursor']
                rotated=directory/'cloud_redirect.old';source.rename(rotated)
                source.write_text('ERROR new log rotation\n')
                third=diagnostics.snapshot(cursor,100)
                self.assertEqual(len(third['entries']),1)
                self.assertIn('rotation',third['entries'][0]['message'])

    def test_diagnostics_redacts_json_secrets_and_preserves_history(self):
        drain()
        with patch.object(diagnostics,'_roots',return_value=[]), \
             patch.object(diagnostics,'_cursors',{}), \
             patch.object(diagnostics,'_events',deque(maxlen=2500)), \
             patch.object(diagnostics,'_serial',0):
            emit('Cloud sync failed: {"refresh_token":"secret-abc","password": "pass123"}', 'error','Cloud')
            forwarded=drain()
            self.assertEqual(len(forwarded),1)
            self.assertNotIn('secret-abc',forwarded[0]['message'])
            self.assertNotIn('pass123',forwarded[0]['message'])
            view=diagnostics.snapshot(0,20)
            self.assertEqual(view['entries'][0]['source'],'Cloud')
            self.assertIn('Cloud sync failed',view['entries'][0]['message'])
            self.assertEqual(len(diagnostics.snapshot(view['cursor'],20)['entries']),0)

    def test_snapshot_rejects_invalid_bounded_arguments(self):
        for bad in (-1, '0', None, True):
            with self.assertRaises(ValueError):diagnostics.snapshot(after=bad)
        for bad in (0, 601, '25', True):
            with self.assertRaises(ValueError):diagnostics.snapshot(limit=bad)
