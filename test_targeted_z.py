import unittest,tempfile
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from targeted_z import PROBES,sample_reports,report_excerpt
class TargetedTests(unittest.TestCase):
 def test_only_confirmed_tables_bounded_queries_and_safe_values(self):
  class Conn:
   def __init__(self): self.calls=[]
   def cursor(self): return self
   def __enter__(self): return self
   def __exit__(self,*args): pass
   def execute(self,sql,params): self.calls.append((sql,params))
   def fetchall(self):
    table=next(t for t in PROBES if 'FROM `'+t+'`' in self.calls[-1][0])
    vals={'cod':7,'data':datetime(2026,10,19),'incasari':Decimal('12.50'),'explicatii':'Raport Z token=SECRET'}
    return [tuple(vals.get(c) for c in PROBES[table][1])]
  schema={t:{'columns':[{'name':c,'key':'PRI' if c=='cod' else ''} for c in cols]} for t,(_,cols) in PROBES.items()}
  conn=Conn(); result=sample_reports(conn,schema)
  self.assertEqual(len(conn.calls),3)
  for sql,params in conn.calls:
   self.assertTrue(sql.startswith('SELECT ')); self.assertIn('ORDER BY `cod` DESC LIMIT %s',sql)
   self.assertLessEqual(params[0],50)
  r=result['produse_registru_casa']['rows'][0]
  self.assertEqual(r['incasari'],'12.50');self.assertNotIn('SECRET',r['explicatii'])
  self.assertEqual(r['data'],'2026-10-19T00:00:00')
 def test_missing_schema_never_queries(self):
  class Conn:
   def cursor(self): raise AssertionError('must not query')
  self.assertTrue(all(r['status']=='schema_missing_or_no_primary_key' for r in sample_reports(Conn(),{}).values()))
 def test_only_z_marked_text_and_bounded_preview(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'raport_z.txt';p.write_text('RAPORT Z\npassword=SECRET\n'+'x'*20000)
   r=report_excerpt(p)
   self.assertNotIn('SECRET',r['preview']);self.assertTrue(r['preview_truncated']);self.assertFalse(r['fiscal_source_verified'])
   self.assertLessEqual(len(r['preview']),4100)
   p.write_text('not a report');self.assertIsNone(report_excerpt(p))
   p=Path(tmp)/'other.txt';p.write_text('RAPORT Z');self.assertIsNone(report_excerpt(p))
 def test_query_error_does_not_leak_credentials(self):
  class Conn:
   def cursor(self): raise RuntimeError('secret=SECRET')
  schema={t:{'columns':[{'name':c,'key':'PRI' if c=='cod' else ''} for c in cols]} for t,(_,cols) in PROBES.items()}
  result=sample_reports(Conn(),schema)
  self.assertNotIn('SECRET',str(result));self.assertTrue(all(r['status']=='error' for r in result.values()))
if __name__=='__main__': unittest.main()
