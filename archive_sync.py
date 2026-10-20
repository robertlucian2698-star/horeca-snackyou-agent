"""Read-only full daily archive transfer. No receipt cursor/config writes."""
import base64
import hashlib
import json
import os
import stat
import threading
import time
from datetime import date
from pathlib import Path
from archive_samples import NAME, regular_path

MAX_FILE = 512 * 1024
MAX_ENTRIES = 10000

def signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

def scan(roots):
    found, errors, complete, seen = [], [], True, set()
    for root in roots:
        root = Path(root).absolute()
        folder = root if root.name.lower() == 'rapoarte_zilnice' else root / 'rapoarte_zilnice'
        if not folder.exists():
            continue
        try:
            if not regular_path(folder):
                errors.append('unsafe_archive'); complete = False; continue
            key = os.path.normcase(str(folder))
            if key in seen: continue
            seen.add(key)
            with os.scandir(folder) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_ENTRIES:
                        errors.append('scan_limit'); complete = False; break
                    match = NAME.fullmatch(entry.name)
                    if not match: continue
                    try:
                        day = date.fromisoformat(match[1]).isoformat()
                        info = os.stat(entry.path, follow_symlinks=False)
                        if not stat.S_ISREG(info.st_mode) or getattr(info,'st_file_attributes',0)&1024:
                            raise ValueError('unsafe_file')
                        found.append((day, Path(entry.path), info))
                    except (OSError, ValueError):
                        errors.append(entry.name); complete = False
        except OSError:
            errors.append('unreadable_archive'); complete = False
    return sorted(found,key=lambda x:(x[0],str(x[1]))), errors, complete and bool(seen)

def sample(path, before, now):
    if now-before.st_mtime < 60: raise ValueError('file_recent')
    if before.st_size > MAX_FILE or not regular_path(path): raise ValueError('file_size_or_path')
    with path.open('rb') as stream:
        opened=os.fstat(stream.fileno()); raw=stream.read(MAX_FILE+1); after=os.fstat(stream.fileno())
    if signature(before)!=signature(opened) or signature(opened)!=signature(after) or len(raw)!=before.st_size:
        raise ValueError('file_changed')
    if not raw.startswith(b'%PDF-'): raise ValueError('not_pdf')
    return {'name':path.name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'content_base64':base64.b64encode(raw).decode('ascii')}

class ArchiveWorker:
    def __init__(self,cfg,folder,discover,send,now=time.time):
        self.cfg=dict(cfg);self.path=Path(folder)/'horeca-archive-ledger.json'
        self.discover,self.send,self.now=discover,send,now
        self.identity=hashlib.sha256((cfg['backend_url']+'\0'+cfg['agent_token']).encode()).hexdigest()
    def save(self,acked):
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps({'identity':self.identity,'acked':acked}),encoding='utf-8')
        try:os.chmod(temp,0o600)
        except OSError:pass
        os.replace(temp,self.path)
    def step(self):
        state={}
        try:state=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        acked=state.get('acked',{}) if isinstance(state,dict) and state.get('identity')==self.identity else {}
        if not isinstance(acked,dict):acked={}
        files,errors,complete=scan(self.discover())
        keys={str(path):hashlib.sha256(repr(signature(info)).encode()).hexdigest() for _,path,info in files}
        acked={p:s for p,s in acked.items() if keys.get(p)==s}
        def progress():
            return {'found':len(files),'confirmed':len(acked),'errors':len(errors),'scan_complete':complete,
                    'first_date':files[0][0] if files else None,'last_date':files[-1][0] if files else None,
                    'complete':complete and len(acked)==len(files) and not errors,'issues':errors[:20]}
        batch=[];paths=[]
        def flush():
            if not batch:return
            result=self.send({'samples':list(batch),'progress':progress()})
            hashes=set(result.get('accepted',[])) if isinstance(result,dict) else set()
            if not all(s['sha256'] in hashes for s in batch):raise RuntimeError('archive_not_acknowledged')
            for path in paths:acked[str(path)]=keys[str(path)]
            self.save(acked);batch.clear();paths.clear()
            time.sleep(0.25)
        self.send({'samples':[],'progress':progress()})
        for _,path,info in files:
            if acked.get(str(path))==keys[str(path)]:continue
            try:item=sample(path,info,self.now())
            except (OSError,ValueError) as exc:
                errors.append(path.name+':'+type(exc).__name__);continue
            batch.append(item);paths.append(path)
            if len(batch)==2:flush()
        flush()
        self.send({'samples':[],'progress':progress()})
        return progress()

def start_worker(cfg,folder):
    import httpx
    import logging
    from diagnostic import discover_pos
    def send(payload):
        with httpx.Client(timeout=20) as client:
            response=client.post(cfg['backend_url'].rstrip('/')+'/pos/daily-reports',
                headers={'X-POS-Token':cfg['agent_token']},json=payload)
            response.raise_for_status();return response.json()
    worker=ArchiveWorker(cfg,folder,discover_pos,send)
    def loop():
        while True:
            try:logging.getLogger('horeca-snackyou').info('Arhiva zilnica: %s',worker.step())
            except Exception as exc:logging.getLogger('horeca-snackyou').warning('Arhiva: %s; reluare automata, bonurile continua',type(exc).__name__)
            time.sleep(300)
    thread=threading.Thread(target=loop,name='daily-archive',daemon=True);thread.start();return thread
