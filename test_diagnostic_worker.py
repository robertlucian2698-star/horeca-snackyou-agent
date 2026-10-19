import json,tempfile,unittest
from pathlib import Path
from diagnostic_worker import DiagnosticWorker,prepare_report
from disk_discovery import disk_candidates,xml_path_hints
class WorkerTests(unittest.TestCase):
 def test_retry_preserves_outbox_and_receipt_files(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);receipt=root/'horeca-snackyou.state.db';receipt.write_bytes(b'UNCHANGED')
   calls=[]; cfg={'agent_token':'SENSITIVE','unitypos_password':'PASSWORD'}
   def collect(c): calls.append(1);return {'database':{},'filesystem':{},'note':'SENSITIVE PASSWORD'}
   worker=DiagnosticWorker(cfg,root,collect,lambda c,r:False,now=lambda:100000)
   self.assertEqual(worker.step(),'pending');self.assertEqual(worker.step(),'pending');self.assertEqual(len(calls),1)
   self.assertNotIn('SENSITIVE',worker.path.read_text());self.assertNotIn('PASSWORD',worker.path.read_text())
   worker.send=lambda c,r:True
   self.assertEqual(worker.step(),'sent');self.assertEqual(worker.step(),'not_due')
   self.assertEqual(receipt.read_bytes(),b'UNCHANGED')
 def test_collection_failure_does_not_touch_receipts(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'horeca-snackyou.state.db';p.write_text('unchanged')
   def fail(cfg): raise RuntimeError('offline')
   worker=DiagnosticWorker({},tmp,fail,lambda c,r:True)
   with self.assertRaises(RuntimeError):worker.step()
   self.assertEqual(p.read_text(),'unchanged')
 def test_send_exception_keeps_report_for_retry(self):
  with tempfile.TemporaryDirectory() as tmp:
   def fail(c,r): raise OSError('offline')
   w=DiagnosticWorker({},tmp,lambda c:{'database':{},'filesystem':{}},fail)
   with self.assertRaises(OSError):w.step()
   self.assertIn('pending',json.loads(w.path.read_text()))
 def test_disk_scan_skips_personal_folders(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'UnityPOS').mkdir();(root/'Users'/'UnityPOS').mkdir(parents=True)
   self.assertEqual(disk_candidates([root]),[root/'UnityPOS'])
 def test_xml_hints_do_not_expose_credentials(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'reports').mkdir()
   (root/'data.xml').write_text('<settings><folder>reports</folder><password>SECRET</password></settings>')
   paths,structure=xml_path_hints(root)
   self.assertEqual(paths,[(root/'reports').resolve()]);self.assertNotIn('SECRET',str(structure))
if __name__=='__main__':unittest.main()
