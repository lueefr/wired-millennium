from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import updates
import update_timer

TZ=timezone(timedelta(hours=-3))


def target(revision='one',artifact='binary-one'):
    return {'revision':revision,'commit':revision,'version':'v1','title':'Fix compatibility','repository':'swwayps/cloudredirect-moon','url':'https://github.com/swwayps/cloudredirect-moon','artifact':{'commit':revision,'blobs':{}},'artifact_id':artifact}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.root_patch=patch.object(updates,'ROOT',self.root);self.root_patch.start()
    def tearDown(self):self.root_patch.stop();self.temp.cleanup()

    def test_fixed_slots_and_late_catch_up_do_not_drift(self):
        at=lambda day,hour,minute=0:datetime(2026,11,day,hour,minute,tzinfo=TZ)
        self.assertEqual(updates.slot(at(12,0,59)),updates.slot(at(11,22,45)))
        self.assertNotEqual(updates.slot(at(12,0,59)),updates.slot(at(12,1)))
        for hour in (1,7,13,19):
            self.assertNotEqual(updates.slot(at(12,hour)-timedelta(seconds=1)),updates.slot(at(12,hour)))
        self.assertEqual(updates.next_check(at(12,22,45)),at(13,1).isoformat())
        self.assertEqual(updates.next_check(at(12,1)),at(12,7).isoformat())
        with patch.object(updates,'snapshot',return_value=target()) as snapshot,patch.object(updates,'installed_version',return_value=None):
            self.assertTrue(updates.check(at(12,22,45)))
            self.assertFalse(updates.check(at(12,22,46)))
            self.assertFalse(updates.check(at(13,0,59)))
            self.assertEqual(snapshot.call_count,2,'One recovery check per repo, no missed-slot backlog')
            self.assertTrue(updates.check(at(13,1)));self.assertEqual(snapshot.call_count,4)

    def test_editing_release_notes_does_not_repeat_the_same_version(self):
        repository={'default_branch':'main'};tip={'sha':'f'*40,'commit':{'message':'Fix compatibility'}}
        release={'tag_name':'v1','html_url':'https://github.com/swwayps/slsteam-moon/releases/tag/v1','body':'Original notes','assets':[{'id':1,'name':'linux.zip','browser_download_url':'https://example.test/linux.zip','updated_at':'2026-11-12'},{'id':2,'name':'linux.zip.sha256','browser_download_url':'https://example.test/linux.zip.sha256','updated_at':'2026-11-12'}]}
        edited={**release,'body':'Corrected release description'}
        with patch.object(updates,'api',side_effect=[repository,tip,release,repository,tip,edited]):
            first=updates.snapshot('slssteam');second=updates.snapshot('slssteam')
        self.assertEqual(first['revision'],second['revision'])

    def test_newest_pending_replaces_previous_and_later_is_persistent(self):
        at=lambda hour:datetime(2026,11,12,hour,tzinfo=TZ)
        with patch.object(updates,'snapshot',return_value=target()),patch.object(updates,'installed_version',return_value=None):updates.check(at(1))
        with patch.object(updates,'snapshot',return_value=target('two','binary-two')),patch.object(updates,'changelog',return_value=['Fix Linux 64-bit support']):updates.check(at(7))
        entry=updates.status()['updates'][0]
        self.assertTrue(entry['installable']);self.assertEqual(entry['changes'],['Fix Linux 64-bit support'])
        updates.respond(entry['component'],entry['revision'],'later')
        self.assertEqual(updates.status()['updates'][0]['decision'],'dismissed')
        with patch.object(updates,'snapshot',return_value=target('three','binary-three')),patch.object(updates,'changelog',return_value=['New update']):updates.check(at(13))
        pending=updates.status()['updates'];self.assertEqual(len(pending),2)
        self.assertTrue(all(item['revision']=='three' for item in pending));self.assertTrue(all(item['decision']=='available' for item in pending))

    def test_source_change_is_not_offered_as_installable(self):
        with patch.object(updates,'snapshot',return_value=target()),patch.object(updates,'installed_version',return_value=None):updates.check(datetime(2026,11,12,1,tzinfo=TZ))
        with patch.object(updates,'snapshot',return_value=target('two','binary-one')),patch.object(updates,'changelog',return_value=['Source change only']):updates.check(datetime(2026,11,12,7,tzinfo=TZ))
        entry=updates.status()['updates'][0];self.assertFalse(entry['installable'])
        with self.assertRaisesRegex(ValueError,'No new installable'):updates.respond(entry['component'],entry['revision'],'download')

    def test_failed_check_is_bounded_to_current_slot(self):
        now=datetime(2026,11,12,22,45,tzinfo=TZ)
        with patch.object(updates,'snapshot',side_effect=OSError('offline')) as snapshot:
            updates.check(now);updates.check(now+timedelta(minutes=1));self.assertEqual(snapshot.call_count,2)
        self.assertIn('offline',updates.state()['repositories']['slssteam']['error'])
        self.assertEqual(updates.next_check(now),'2026-11-13T01:00:00-03:00')

    def test_download_requires_current_consent_and_is_detached(self):
        with updates.Locked():
            value=updates.state();value['repositories']['slssteam']={'pending':{'revision':'r1','decision':'available','installable':True,'target':target()}};updates.save(value)
        with self.assertRaisesRegex(ValueError,'outdated'):updates.respond('slssteam','old','download')
        with patch.object(updates.subprocess,'Popen',return_value=Mock(pid=1234)) as spawn:
            updates.respond('slssteam','r1','download')
            self.assertTrue(spawn.call_args.kwargs['start_new_session']);self.assertNotIn('LD_AUDIT',spawn.call_args.kwargs['env'])
            self.assertEqual(updates.status()['updates'][0]['decision'],'preparing')
            updates.respond('slssteam','r1','download');self.assertEqual(spawn.call_count,1)

    def test_binary_verification_rejects_wrong_architecture(self):
        binary=self.root/'lib.so';content=bytearray(20);content[:4]=b'\x7fELF';content[4]=1;content[18:20]=(3).to_bytes(2,'little');binary.write_bytes(content)
        self.assertEqual(updates.elf_arch(binary),32)
        with patch.object(updates,'steam_arch',return_value=64):
            with self.assertRaisesRegex(ValueError,'architecture'):updates.verify_arch([binary])

    def test_staging_checks_blob_integrity_and_does_not_install(self):
        content=bytearray(20);content[:4]=b'\x7fELF';content[4]=2;content[18:20]=(62).to_bytes(2,'little');content=bytes(content)
        files={'cloud_redirect.so':content,'cloud_redirect_cli':content,'LICENSE':b'MIT'}
        blobs={name:hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() for name,body in files.items()}
        candidate=target();candidate['artifact']['blobs']=blobs
        def fetch(url,path,*args):path.write_bytes(files[path.name])
        with patch.object(updates,'fetch',side_effect=fetch),patch.object(updates,'steam_arch',return_value=64):
            directory=updates.prepare('cloudredirect',candidate)
        self.assertTrue((directory/'plan.json').exists());self.assertTrue((directory/'cloud_redirect.so').exists())
        self.assertFalse((self.root/'cloudredirect.json').exists(),'Staging must not change installed receipts')

    def test_approved_cloud_update_installs_only_verified_staged_files(self):
        content=bytearray(20);content[:4]=b'\x7fELF';content[4]=2;content[18:20]=(62).to_bytes(2,'little');content=bytes(content)
        files={'cloud_redirect.so':content,'cloud_redirect_cli':content,'LICENSE':b'MIT'}
        blobs={name:hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() for name,body in files.items()}
        candidate=target();candidate['artifact']['blobs']=blobs
        def fetch(url,path,*args):path.write_bytes(files[path.name])
        with patch.object(updates,'fetch',side_effect=fetch),patch.object(updates,'steam_arch',return_value=64):directory=updates.prepare('cloudredirect',candidate)
        destination=self.root/'home/.local/share/CloudRedirect';destination.mkdir(parents=True)
        (destination/'cloud_redirect.so').write_bytes(b'previous library')
        value=updates.state();value['repositories']['cloudredirect']={'pending':{'revision':'one','decision':'queued','directory':str(directory)}};updates.save(value)
        with patch.object(updates,'steam_running',return_value=False),patch.object(updates,'steam_arch',return_value=64),patch.object(updates.Path,'home',return_value=self.root/'home'):
            self.assertTrue(updates.apply_pending())
        self.assertEqual((destination/'cloud_redirect.so').read_bytes(),content)
        self.assertEqual((destination/'cloud_redirect.so.wired-backup').read_bytes(),b'previous library')
        self.assertEqual(updates.state()['repositories']['cloudredirect']['pending']['decision'],'installed')
        (directory/'cloud_redirect.so').write_bytes(b'modified')
        value=updates.state();value['repositories']['cloudredirect']['pending']['decision']='queued';updates.save(value)
        with patch.object(updates,'steam_running',return_value=False),patch.object(updates.Path,'home',return_value=self.root/'home'):
            updates.apply_pending()
        self.assertEqual(updates.state()['repositories']['cloudredirect']['pending']['decision'],'error')
        self.assertEqual((destination/'cloud_redirect.so').read_bytes(),content)

    def test_running_steam_blocks_installation(self):
        with patch.object(updates,'steam_running',return_value=True):self.assertFalse(updates.apply_pending())

    def test_systemd_calendar_is_fixed_and_persistent(self):
        with patch.object(update_timer,'unit_directory',return_value=self.root),patch.object(update_timer,'command',return_value=True) as command:
            self.assertTrue(update_timer.install(self.root/'plugin'))
            text=(self.root/update_timer.NAMES[1]).read_text()
            self.assertIn('OnCalendar=*-*-* 01,07,13,19:00:00',text);self.assertIn('Persistent=true',text)
            self.assertNotIn('OnUnitActiveSec',text)
            update_timer.remove();self.assertFalse((self.root/update_timer.NAMES[1]).exists())
