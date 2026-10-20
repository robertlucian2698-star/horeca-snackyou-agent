import os,tempfile,unittest
from pathlib import Path
from archive_sync import ArchiveWorker
class ArchiveTests(unittest.TestCase):
 def make(self,root,n):
  folder=root/'UnityPOS'/'rapoarte_zilnice';folder.mkdir(parents=True,exist_ok=True)
  for i in range(n):
   p=folder/f'raport_zilnic-{i}-2026-01-{i%28+1:02}.pdf';p.write_bytes(b'%PDF-1.4\n'+str(i).encode());os.utime(p,(100,100))
  return folder
 def test_all_files_restart_idempotence_and_config_untouched(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();folder=self.make(root,45);config=root/'horeca-snackyou.config.json';config.write_text('unchanged')
   packets=[]
   def send(p):packets.append(p);return {'accepted':[s['sha256'] for s in p['samples']]}
   cfg={'backend_url':'https://synthetic.invalid','agent_token':'synthetic'}
   w=ArchiveWorker(cfg,root,lambda:[folder.parent],send,now=lambda:1000)
   result=w.step();self.assertTrue(result['complete']);self.assertEqual(result['confirmed'],45)
   docs=[s for p in packets for s in p['samples']];self.assertEqual(len(docs),45);self.assertTrue(all(len(p['samples'])<=2 for p in packets))
   packets.clear();ArchiveWorker(cfg,root,lambda:[folder.parent],send,now=lambda:1000).step()
   self.assertFalse(any(p['samples'] for p in packets));self.assertEqual(config.read_text(),'unchanged')
 def test_failure_resumes_only_unacknowledged(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();folder=self.make(root,5);calls=[]
   def broken(p):
    if p['samples']:
     calls.append(p)
     if len(calls)==2:return {'accepted':[]}
    return {'accepted':[s['sha256'] for s in p['samples']]}
   cfg={'backend_url':'https://synthetic.invalid','agent_token':'synthetic'}
   with self.assertRaises(RuntimeError):ArchiveWorker(cfg,root,lambda:[folder],broken,now=lambda:1000).step()
   resent=[]
   def send(p):resent.extend(p['samples']);return {'accepted':[s['sha256'] for s in p['samples']]}
   self.assertTrue(ArchiveWorker(cfg,root,lambda:[folder],send,now=lambda:1000).step()['complete'])
   self.assertEqual(len(resent),3)
 def test_invalid_file_is_not_reported_as_complete(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();folder=self.make(root,1);p=next(folder.iterdir());p.write_bytes(b'not-pdf');os.utime(p,(100,100))
   w=ArchiveWorker({'backend_url':'synthetic','agent_token':'test'},root,lambda:[folder],lambda p:{'accepted':[]},now=lambda:1000)
   result=w.step();self.assertEqual(result['errors'],1);self.assertFalse(result['complete'])
if __name__=='__main__':unittest.main()
