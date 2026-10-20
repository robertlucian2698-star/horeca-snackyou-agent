"""Read only UnityPOS catalog; never touches receipt queue or configuration."""
import logging
import threading
import time

MAX_PRODUCTS=10000
QUERY='SELECT cod,denumire,categorie,gestiune,um FROM gestiune ORDER BY cod LIMIT 10001'

def read_catalog(cfg,connect=None):
 if connect is None:
  import pymysql
  import pymysql.cursors
  connect=lambda:pymysql.connect(host=cfg['unitypos_host'],port=int(cfg['unitypos_port']),user=cfg['unitypos_user'],password=cfg['unitypos_password'],database=cfg['unitypos_database'],charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,connect_timeout=5,read_timeout=5,write_timeout=5,autocommit=True)
 connection=connect()
 try:
  with connection.cursor() as cursor:
   cursor.execute(QUERY);rows=cursor.fetchall()
  if len(rows)>MAX_PRODUCTS:raise ValueError('catalog_limit')
  products=[{'code':int(r['cod']),'name':str(r['denumire'] or '').strip(),'category':str(r.get('categorie') or ''),'department':str(r.get('gestiune') or ''),'unit':str(r.get('um') or '')} for r in rows]
  if any(not p['name'] for p in products) or len({p['code'] for p in products})!=len(products):raise ValueError('invalid_catalog')
  return {'products':products}
 finally:connection.close()

def sync_catalog(cfg,read=read_catalog,send=None):
 payload=read(cfg)
 if send is None:
  import httpx
  def send(body):
   with httpx.Client(timeout=20) as c:
    r=c.post(cfg['backend_url'].rstrip('/')+'/pos/catalog',headers={'X-POS-Token':cfg['agent_token']},json=body)
    r.raise_for_status();return r.json()
 reply=send(payload)
 if reply.get('accepted')!=len(payload['products']):raise ValueError('catalog_ack')
 return reply['accepted']

def start_worker(cfg):
 config=dict(cfg)
 def loop():
  while True:
   try:logging.getLogger('horeca-snackyou').info('Catalog UnityPOS: %s produse confirmate',sync_catalog(config))
   except Exception as exc:logging.getLogger('horeca-snackyou').warning('Catalog: %s; reîncercare automată, bonurile continuă',type(exc).__name__)
   time.sleep(300)
 thread=threading.Thread(target=loop,name='pos-catalog',daemon=True);thread.start();return thread
