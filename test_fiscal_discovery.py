import os
import tempfile
import unittest
from pathlib import Path
from fiscal_discovery import collect_fiscal_sources
from diagnostic_worker import prepare_report,MAX_BYTES
import json

class FiscalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name).resolve();self.printer=self.root/'printer'/'UnityPrinter';self.printer.mkdir(parents=True)
  self.driver=self.root/'FiscalDriver';self.driver.mkdir()
 def config(self,content):
  (self.printer/'data.xml').write_text(content)
 def test_follows_executable_parent_and_reads_z_log(self):
  exe=self.driver/'driver.exe';exe.write_bytes(b'NEVER EXECUTE')
  self.config(f'<data><driver>TestDriver</driver><driver_path>{exe}</driver_path><password>SECRET</password></data>')
  (self.driver/'journal.log').write_text('RAPORT FISCAL ZILNIC\nZ NR:0507\nNUMERAR731\nCARD641\nTOTAL1372')
  r=collect_fiscal_sources([self.root])
  self.assertNotIn('SECRET',str(r));self.assertEqual(len(r['text_candidates']),1)
  self.assertIn('0507',r['text_candidates'][0]['preview']);self.assertFalse(r['fiscal_source_verified'])
 def test_entity_config_is_not_expanded(self):
  self.config('<!DOCTYPE data [<!ENTITY x SYSTEM "file:///etc/passwd">]><data><driver>&x;</driver></data>')
  self.assertEqual(collect_fiscal_sources([self.root])['configs'][0]['fields'],{})
 def test_unc_and_drive_root_are_not_followed(self):
  self.config('<data><driver_path>\\\\host\\share</driver_path><bf_path>'+self.root.anchor+'</bf_path></data>')
  r=collect_fiscal_sources([self.root]);self.assertEqual(len(r['locations']),1)
 def test_no_config_or_database_content_uploaded(self):
  self.config('<data><driver>Printer</driver></data>')
  for name in ('settings.xml','password.txt','export.sql','source.php'):
   (self.printer/name).write_text('RAPORT FISCAL ZILNIC SECRET')
  self.assertEqual(collect_fiscal_sources([self.root])['text_candidates'],[])
 def test_tail_read_and_redaction(self):
  self.config('<data/>')
  (self.printer/'fiscal.log').write_text('x'*40000+'\nZ NR:0507\npassword=PRIVATE\n<token>SECRET</token>')
  r=collect_fiscal_sources([self.root]);x=r['text_candidates'][0]
  self.assertGreater(x['read_offset_bytes'],0);self.assertNotIn('PRIVATE',x['preview']);self.assertNotIn('SECRET',x['preview'])
 def test_samples_globally_bounded(self):
  self.config('<data/>')
  for i in range(30):(self.printer/f'{i}.txt').write_text('Z NR:0507')
  r=collect_fiscal_sources([self.root]);self.assertEqual(len(r['text_candidates']),3);self.assertTrue(r['text_scan_limited'])
 def test_daily_report_alone_is_not_fiscal_candidate(self):
  self.config('<data/>');(self.printer/'daily.txt').write_text('Raport Zilnic TOTAL1372')
  self.assertEqual(collect_fiscal_sources([self.root])['text_candidates'],[])
 def test_inventory_does_not_block_payload(self):
  report={'database':{},'filesystem':{},'fiscal_discovery':{'locations':[{'files':[{'path':'x'*512} for _ in range(80)]} for _ in range(6)]}}
  result=prepare_report(report,{})
  self.assertLess(len(json.dumps(result).encode()),MAX_BYTES)

if __name__=='__main__':unittest.main()
