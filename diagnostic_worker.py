"""Independent diagnostic worker: own spool, no receipt state/cursor access."""
import json
import os
import threading
import time
from pathlib import Path

MAX_BYTES = 250 * 1024


def prepare_report(report, cfg):
    # Never send the actual connection credentials, including in free-form excerpts.
    raw = json.dumps(report, ensure_ascii=False, allow_nan=False)
    for key in ('agent_token', 'unitypos_password'):
        secret = cfg.get(key)
        if isinstance(secret, str) and len(secret) >= 4:
            raw = raw.replace(json.dumps(secret, ensure_ascii=False)[1:-1], '[REDACTED]')
    clean = json.loads(raw)
    if len(raw.encode()) > MAX_BYTES:
        clean.get('database', {}).pop('tables', None)
        clean['size_limited'] = True
        raw = json.dumps(clean, ensure_ascii=False)
    if len(raw.encode()) > MAX_BYTES:
        for folder in clean.get('filesystem', {}).get('folders', []):
            for file in folder.get('files', []):
                file.pop('z_text_candidate', None)
        clean['excerpts_omitted'] = True
    if len(json.dumps(clean, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError('diagnostic_limit')
    return clean


class DiagnosticWorker:
    def __init__(self, cfg, folder, collect, send, now=time.time):
        self.cfg = dict(cfg)
        self.path = Path(folder) / 'horeca-diagnostic-outbox.json'
        self.collect, self.send, self.now = collect, send, now

    def save(self, state):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        try: os.chmod(tmp, 0o600)
        except OSError: pass
        os.replace(tmp, self.path)

    def step(self):
        state = {}
        if self.path.exists():
            try: state = json.loads(self.path.read_text(encoding='utf-8'))
            except (ValueError, OSError): state = {}
        if not isinstance(state, dict):
            state = {}
        if not state.get('pending') and state.get('last_sent') and self.now() - state['last_sent'] < 21600:
            return 'not_due'
        if not state.get('pending'):
            state['pending'] = prepare_report(self.collect(self.cfg), self.cfg)
            self.save(state)
        if self.send(self.cfg, state['pending']):
            self.save({'last_sent': self.now()})
            return 'sent'
        return 'pending'


def start_worker(cfg, folder):
    from diagnostic import collect_report
    import httpx
    def send(config, report):
        with httpx.Client(timeout=20, headers={'X-POS-Token': config['agent_token']}) as client:
            r = client.post(config['backend_url'].rstrip('/') + '/pos/diagnostics', json=report)
            return r.status_code == 200
    worker = DiagnosticWorker(cfg, folder, collect_report, send)
    def loop():
        import logging
        while True:
            try:
                result = worker.step()
                logging.getLogger('horeca-snackyou').info('Diagnostic local/cloud: %s', result)
            except Exception as exc:
                logging.getLogger('horeca-snackyou').warning('Diagnostic separat: %s (bonurile continua)', type(exc).__name__)
            time.sleep(900)
    thread = threading.Thread(target=loop, name='pos-diagnostic', daemon=True)
    thread.start()
    return thread
