import unittest
from catalog_sync import read_catalog,sync_catalog,QUERY
class CatalogTests(unittest.TestCase):
 def connection(self,rows):
  class Cursor:
   def __enter__(s):return s
   def __exit__(s,*args):pass
   def execute(s,q):self.assertEqual(q,QUERY);self.assertTrue(q.startswith('SELECT '))
   def fetchall(s):return rows
  class Connection:
   closed=False
   def cursor(s):return Cursor()
   def close(s):s.closed=True
  return Connection()
 def test_new_product_without_sale(self):
  c=self.connection([dict(cod=123,denumire='Suc nou',um='buc')]);payload=read_catalog({},lambda:c)
  self.assertEqual(payload['products'][0]['name'],'Suc nou');self.assertTrue(c.closed)
  self.assertEqual(sync_catalog({},lambda _:payload,lambda p:{'accepted':len(p['products'])}),1)
 def test_limit_does_not_publish_partial(self):
  c=self.connection([dict(cod=1,denumire='Test')]*10001)
  with self.assertRaises(ValueError):read_catalog({},lambda:c)
  self.assertTrue(c.closed)
 def test_ack_failure_retries_next_full_snapshot(self):
  p={'products':[{'code':1,'name':'Test'}]}
  with self.assertRaises(ValueError):sync_catalog({},lambda _:p,lambda p:{'accepted':0})
  self.assertEqual(sync_catalog({},lambda _:p,lambda p:{'accepted':1}),1)
 def test_duplicate_rejected(self):
  c=self.connection([dict(cod=1,denumire='A'),dict(cod=1,denumire='B')])
  with self.assertRaises(ValueError):read_catalog({},lambda:c)
