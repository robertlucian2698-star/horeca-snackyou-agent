import base64
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
from archive_samples import collect_archive_samples, MAX_FILE_BYTES
from diagnostic_worker import DiagnosticWorker, prepare_report, MAX_BYTES

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.folder = self.root / 'rapoarte_zilnice'
        self.folder.mkdir()
    def pdf(self, number, day, data=b'%PDF-1.4\nSYNTHETIC'):
        p = self.folder / f'raport_zilnic-{number}-{day}.pdf'
        p.write_bytes(data)
        os.utime(p, (100, 100))
        return p
    def test_newest_dates_beyond_general_scan_cap(self):
        for i in range(250): self.pdf(i, '2025-01-01')
        self.pdf(251, '2026-10-18'); self.pdf(252, '2026-10-19')
        r = collect_archive_samples([self.root, self.folder], now=1000)
        self.assertEqual(r['archives'][0]['matched_files'], 252)
        self.assertEqual(len(r['archives']), 1)
        self.assertEqual([s['date'] for s in r['samples']], ['2026-10-19','2026-10-18'],r)
        self.assertEqual(base64.b64decode(r['samples'][0]['content_base64']), b'%PDF-1.4\nSYNTHETIC')
        self.assertFalse(r['fiscal_source_verified'])
    def test_invalid_large_and_recent_are_skipped(self):
        self.pdf(1,'2026-10-19',b'%PDF-'+b'x'*MAX_FILE_BYTES)
        self.pdf(2,'2026-10-18',b'not a pdf')
        p=self.pdf(3,'2026-10-17'); os.utime(p,(999,999))
        self.pdf(4,'2026-10-16')
        r=collect_archive_samples([self.root],now=1000)
        self.assertEqual(len(r['samples']),1,r)
        self.assertEqual({s['reason'] for s in r['skipped']},{'too_large','not_pdf','still_recent'})
    @unittest.skipIf(os.name=='nt','Windows junction test handled separately')
    def test_symlink_folder_rejected(self):
        self.pdf(1,'2026-10-19')
        other=self.root/'other';other.mkdir()
        (other/'rapoarte_zilnice').symlink_to(self.folder,target_is_directory=True)
        self.assertEqual(collect_archive_samples([other])['samples'],[])
    def test_does_not_read_unrelated_files(self):
        (self.folder/'config.pdf').write_bytes(b'%PDF-SECRET')
        (self.folder/'raport_zilnic-1-2026-99-99.pdf').write_bytes(b'%PDF-bad')
        self.assertEqual(collect_archive_samples([self.root])['samples'],[])
    def test_payload_budget_retains_pdf_samples(self):
        self.pdf(1,'2026-10-19',b'%PDF-'+b'x'*(MAX_FILE_BYTES-5))
        self.pdf(2,'2026-10-18',b'%PDF-'+b'x'*(MAX_FILE_BYTES-5))
        r={'database':{'tables':['x'*200000]},'filesystem':{},'daily_archive':collect_archive_samples([self.root],now=1000)}
        out=prepare_report(r,{})
        self.assertLess(len(json.dumps(out).encode()),MAX_BYTES)
        self.assertEqual(len(out['daily_archive']['samples']),2)
    def test_changed_file_is_not_uploaded(self):
        self.pdf(1,'2026-10-19')
        with patch('archive_samples.os.fstat', return_value=SimpleNamespace(st_dev=-1,st_ino=-1,st_size=0,st_mtime_ns=0)):
            result=collect_archive_samples([self.root],now=1000)
        self.assertEqual(result['samples'],[])
        self.assertEqual(result['skipped'][0]['reason'],'changed_during_read')
    def test_windows_reparse_folder_is_rejected(self):
        self.pdf(1,'2026-10-19')
        original=Path.lstat
        def info(path):
            if path == self.folder:
                return SimpleNamespace(st_mode=0o40755,st_file_attributes=1024)
            return original(path)
        with patch.object(Path,'lstat',info):
            self.assertEqual(collect_archive_samples([self.root])['samples'],[])
    def test_content_inspection_is_bounded(self):
        for i in range(30): self.pdf(i,'2026-10-19',b'invalid')
        result=collect_archive_samples([self.root],now=1000)
        self.assertEqual(len(result['skipped']),20)
        self.assertTrue(result['selection_limited'])
    def test_upgrade_collects_without_waiting_six_hours(self):
        w=DiagnosticWorker({},self.root,lambda c:{'database':{},'filesystem':{}},lambda c,r:True,now=lambda:1000)
        w.save({'last_sent':999})
        self.assertEqual(w.step(),'sent')
        self.assertEqual(w.step(),'not_due')
    def test_old_pending_is_sent_before_new_collection(self):
        sent=[]
        w=DiagnosticWorker({},self.root,lambda c:{'database':{},'filesystem':{},'new':True},lambda c,r:sent.append(r) or True,now=lambda:1000)
        w.save({'pending':{'old':True}})
        self.assertEqual(w.step(),'sent');self.assertEqual(w.step(),'sent')
        self.assertTrue(sent[0]['old']);self.assertTrue(sent[1]['new'])

if __name__=='__main__':unittest.main()
