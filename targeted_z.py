"""Bounded read-only probes for the supplied UnityPOS schema."""
import re
from datetime import date, datetime
from decimal import Decimal
PROBES = {
 'produse_registru_casa': (50, ('cod','cod_rc','data','nr_act','nr_anexa','explicatii','incasari','plati','generat_automat')),
 'registru_casa': (10, ('cod','data','cont','sold_precedent','rulaj','sold_final','grupeaza_z','finalizat')),
 'istoric_orar': (20, ('cod','ora_deschidere','ora_inchidere')),
}
def redact(text):
 return re.sub(r'(?i)((?:password|parola|token|secret|api_key)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', text)
def cell(value):
 if isinstance(value,(date,datetime)): return value.isoformat()
 if isinstance(value,Decimal): return str(value)
 if isinstance(value,str): return redact(value[:1024])
 if value is None or isinstance(value,(int,float,bool)): return value
 return '[unsupported]'
def sample_reports(conn,tables):
 results={}
 for table,(limit,columns) in PROBES.items():
  schema=tables.get(table,{}).get('columns',[])
  names={c['name'] for c in schema}
  indexed=any(c['name']=='cod' and c['key']=='PRI' for c in schema)
  if not set(columns)<=names or not indexed:
   results[table]={'status':'schema_missing_or_no_primary_key'}; continue
  try:
   with conn.cursor() as cursor:
    projection=', '.join('LEFT(`'+c+'`,1024)' if c in ('explicatii','nr_act','nr_anexa','cont') else '`'+c+'`' for c in columns)
    cursor.execute('SELECT '+projection+' FROM `'+table+'` ORDER BY `cod` DESC LIMIT %s',(limit,))
    rows=cursor.fetchall()
   results[table]={'status':'ok','limit':limit,'rows':[{k:cell(v) for k,v in zip(columns,row)} for row in rows]}
  except Exception as exc:
   results[table]={'status':'error','error_type':type(exc).__name__,'mysql_code':exc.args[0] if exc.args and type(exc.args[0]) is int else None}
 return results

def report_excerpt(path):
 if path.suffix.lower() not in ('.txt','.xml','.csv'): return None
 if not re.search(r'fiscal|raport.?z|report.?z|z.?report',path.name.lower()): return None
 with path.open('rb') as f: raw=f.read(16384)
 if b'\x00' in raw: return None
 text=raw.decode('utf-8',errors='replace')
 if not re.search(r'(?i)raport\s*(?:fiscal\s*)?z\b|z\s*report\b|<raportz',text): return None
 return {'marker':'report_z_text','preview':redact(text[:4000]),'preview_truncated':len(text)>4000 or len(raw)==16384,'fiscal_source_verified':False}
