#!/usr/bin/env python3
"""
HORECA SNACKYOU — agent casă de marcat (UnityPOS -> cloud, 24/7).

Rulează pe PC-ul din local (cel cu UnityPOS). Citește baza de date UnityPOS
LOCAL (root@localhost) și trimite bonurile noi în cloud prin internet (HTTPS
OUTBOUND). Nu deschide niciun port. Nu depinde de aceeași rețea ca telefonul.

De ce merge de oriunde: agentul <-> cloud prin internet; telefonul <-> cloud
prin internet. PC-ul local nu trebuie să fie accesibil din exterior.

Comenzi (rulate din CMD sau prin dublu-click pe .exe):
  horeca-snackyou.exe            (fără argument) -> setup dacă nu e configurat,
                                  altfel pornește sync-ul continuu
  horeca-snackyou.exe setup       configurare ghidată (o singură dată)
  horeca-snackyou.exe run         pornește sync-ul continuu
  horeca-snackyou.exe sync-once   o singură iterație (test)
  horeca-snackyou.exe status      arată starea locală
  horeca-snackyou.exe install     pornire automată cu Windows (Task Scheduler)
  horeca-snackyou.exe uninstall   dezactivează pornirea automată

Logica de rețea/queue e preluată din agentul dovedit din PASUL 5 (cursor dublu +
queue durabilă + backoff + dead-letter) și întărită după review adversarial
(2026-08-05): Decimal->float, 401/403 = retry nu dead-letter, autostart fără
elevare, fallback dir scriibil, mesaje clare, single-instance lock.
"""
from __future__ import annotations

import argparse
import decimal
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# UTF-8 la consolă (diacritice RO pe Windows cp1252 ar crăpa altfel)
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | horeca-snackyou | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("horeca-snackyou")

# ─── Constante ────────────────────────────────────────────────────────────────
AGENT_VERSION = "1.0.5"
APP_NAME = "HorecaSnackYou"

# Cloud SnackYou — baked. Se poate suprascrie cu env HORECA_BACKEND_URL / config.
DEFAULT_BACKEND_URL = "https://snackyou-backend.fly.dev/api/v1"

BATCH_SIZE = 200          # rânduri citite/trimise per batch
SYNC_INTERVAL = 30        # secunde între cicluri (steady-state)
MAX_CATCHUP_ITERS = 400   # protecție: max 400*200 = 80.000 rânduri per ciclu
BACKOFF_BASE = 5          # secunde
BACKOFF_CAP = 300         # max 5 min între retry-uri
MAX_RETRY = 8             # 5xx persistent peste atât -> dead-letter (anti head-of-line)


class _SetupAborted(Exception):
    """Ridicat când utilizatorul întrerupe configurarea (sau stdin EOF)."""


# ─── Locație fișiere (lângă .exe dacă e scriibil; altfel %LOCALAPPDATA%) ──────
def app_dir() -> Path:
    """Folderul unde stă .exe-ul (sau scriptul în dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _is_writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        t = d / ".hs_write_test"
        t.write_text("x", encoding="utf-8")
        t.unlink()
        return True
    except Exception:
        return False


def data_dir() -> Path:
    """Config + stare: lângă exe dacă se poate scrie; altfel %LOCALAPPDATA%.
    (Program Files nu e scriibil ne-elevat -> fallback, nu crash.)"""
    here = app_dir()
    if _is_writable(here):
        return here
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    d = Path(base) / "HorecaSnackYou"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return Path(os.path.expanduser("~"))


_DATA_DIR = data_dir()
CONFIG_PATH = _DATA_DIR / "horeca-snackyou.config.json"
STATE_DB = str(_DATA_DIR / "horeca-snackyou.state.db")


# ─── Config ──────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "backend_url": DEFAULT_BACKEND_URL,
    "agent_token": "",
    "unitypos_host": "127.0.0.1",
    "unitypos_port": 3306,
    "unitypos_user": "root",
    "unitypos_password": "",
    "unitypos_database": "unitypos",
    "sync_interval_seconds": SYNC_INTERVAL,
    "batch_size": BATCH_SIZE,
}


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning("config.json ilizibil (%s) — folosesc valorile implicite", type(e).__name__)
    if os.getenv("HORECA_BACKEND_URL"):
        cfg["backend_url"] = os.environ["HORECA_BACKEND_URL"]
    if os.getenv("HORECA_AGENT_TOKEN"):
        cfg["agent_token"] = os.environ["HORECA_AGENT_TOKEN"]
    cfg["backend_url"] = str(cfg["backend_url"]).rstrip("/")
    # Coerciții numerice tolerante — o valoare greșită NU mai crapă tot agentul.
    cfg["unitypos_port"] = _to_int(cfg.get("unitypos_port"), 3306)
    cfg["batch_size"] = _to_int(cfg.get("batch_size"), BATCH_SIZE)
    # floor 5s: un interval negativ/0 (config editat greșit) ar crăpa time.sleep -> bucla 24/7 moare
    cfg["sync_interval_seconds"] = max(5, _to_int(cfg.get("sync_interval_seconds"), SYNC_INTERVAL))
    if cfg["backend_url"].startswith("http://"):
        log.warning("backend_url e HTTP (necriptat) — token-ul ar circula în clar. Folosește https://.")
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    # Best-effort: restrânge permisiunile (conține token + parolă MySQL).
    try:
        if sys.platform.startswith("win"):
            user = os.getenv("USERNAME")
            if user:
                subprocess.run(["icacls", str(CONFIG_PATH), "/inheritance:r", "/grant:r", f"{user}:F"],
                               capture_output=True, text=True)
        else:
            os.chmod(CONFIG_PATH, 0o600)
    except Exception:
        pass
    log.info("Configurare salvată: %s", CONFIG_PATH)


# ─── Stare locală (SQLite: cursoare + queue durabilă + dead-letter) ───────────
def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(STATE_DB, timeout=10)
    conn.execute("CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT)")
    conn.execute("""CREATE TABLE IF NOT EXISTS queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload TEXT NOT NULL,
        max_cod INTEGER NOT NULL DEFAULT 0,
        retry_count INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT NOT NULL DEFAULT (datetime('now')),
        last_error TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS dead_letter (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload TEXT NOT NULL, max_cod INTEGER, last_error TEXT,
        failed_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.commit()
    return conn


def get_state(key: str, default: int = 0) -> int:
    conn = _db()
    row = conn.execute("SELECT v FROM state WHERE k=?", (key,)).fetchone()
    conn.close()
    return int(row[0]) if row else default


def set_state(key: str, value: int) -> None:
    conn = _db()
    conn.execute("INSERT INTO state (k,v) VALUES (?,?) "
                 "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, str(value)))
    conn.commit()
    conn.close()


def get_state_str(key: str) -> str | None:
    conn = _db()
    row = conn.execute("SELECT v FROM state WHERE k=?", (key,)).fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def set_state_str(key: str, value: str) -> None:
    conn = _db()
    conn.execute("INSERT INTO state (k,v) VALUES (?,?) "
                 "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))
    conn.commit()
    conn.close()


def get_last_error() -> str | None:
    return get_state_str("last_agent_error")


def set_last_error(msg: str | None) -> None:
    set_state_str("last_agent_error", (msg or "")[:300])


def _now_str() -> str:
    return datetime.now().strftime("%d.%m %H:%M:%S")


def queue_len() -> int:
    conn = _db()
    n = conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
    conn.close()
    return n


def dead_letter_len() -> int:
    conn = _db()
    n = conn.execute("SELECT COUNT(*) FROM dead_letter").fetchone()[0]
    conn.close()
    return n


def enqueue(bonuri: list[dict], vanzari: list[dict], max_cod: int) -> None:
    conn = _db()
    conn.execute(
        "INSERT INTO queue (payload, max_cod) VALUES (?, ?)",
        # default=str = plasă de siguranță pt orice tip neașteptat (Decimal e deja float).
        (json.dumps({"bonuri": bonuri, "vanzari": vanzari}, default=str), max_cod),
    )
    conn.commit()
    conn.close()


# ─── UnityPOS read (local) — SQL IDENTIC cu sync_service dovedit ─────────────
def unitypos_connect(cfg: dict):
    import pymysql
    import pymysql.cursors
    return pymysql.connect(
        host=cfg["unitypos_host"], port=int(cfg["unitypos_port"]),
        user=cfg["unitypos_user"], password=cfg["unitypos_password"],
        database=cfg["unitypos_database"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
    )


def test_unitypos(cfg: dict) -> tuple[bool, str | None, str | None]:
    """Testează conexiunea. Returnează (ok, versiune_mysql, eroare)."""
    try:
        conn = unitypos_connect(cfg)
        try:
            cur = conn.cursor()
            cur.execute("SELECT VERSION() AS v")
            ver = cur.fetchone()["v"]
            return True, str(ver), None
        finally:
            conn.close()
    except Exception as e:
        return False, None, str(e)[:200]


def read_unitypos(cfg: dict, since_cod: int) -> tuple[list[dict], list[dict]]:
    """Citește bonuri/vânzări noi (cod > since_cod). STRICT READ-ONLY (SELECT)."""
    conn = unitypos_connect(cfg)
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT cod, cod_bon, data, valoare, total_ftva, total_tva,
                      ospatar, plata, masa, sala, discount_valoric
               FROM bonuri WHERE cod > %s ORDER BY cod LIMIT %s""",
            (since_cod, int(cfg["batch_size"])),
        )
        bonuri = [_serialize(r) for r in cur.fetchall()]
        if not bonuri:
            return [], []
        cods = [b["cod"] for b in bonuri]
        ph = ",".join(["%s"] * len(cods))
        cur.execute(
            f"""SELECT v.cod, v.cod_bon, v.denumire, v.categorie, v.gestiune,
                       v.cantitate, v.pret, v.pret AS valoare, v.um, v.tva, b.data
                FROM vanzari v INNER JOIN bonuri b ON b.cod = v.cod_bon
                WHERE v.cod_bon IN ({ph})""",
            cods,
        )
        vanzari = [_serialize(r) for r in cur.fetchall()]
        return bonuri, vanzari
    finally:
        conn.close()


def read_registru_casa(cfg: dict, since_cod: int) -> list[dict]:
    """Citește registrul de casă nou (cod > since_cod). READ ONLY.
    SELECT * ca să capturăm toate coloanele (fond de casă, rulaje, solduri, Z)."""
    conn = unitypos_connect(cfg)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM registru_casa WHERE cod > %s ORDER BY cod LIMIT %s",
            (since_cod, int(cfg["batch_size"])),
        )
        return [_serialize(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _serialize(row: dict) -> dict:
    """MariaDB DECIMAL -> float, datetime -> isoformat. (Fără asta, coloanele bani
    ies ca decimal.Decimal și json.dumps crapă -> nimic nu s-ar sincroniza.)"""
    out = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _synthetic(since_cod: int) -> tuple[list[dict], list[dict]]:
    """Date sintetice pentru --dry-run. Folosește Decimal ca UnityPOS real,
    ca să testeze și calea de serializare (nu doar float-uri curate)."""
    c = since_cod + 1
    D = decimal.Decimal
    bonuri = [{"cod": c, "cod_bon": f"B{c}", "data": datetime(2026, 8, 5, 12, 0, 0),
               "valoare": D("42.00"), "total_ftva": D("35.29"), "total_tva": D("6.71"),
               "ospatar": "Demo", "plata": "card", "masa": "1", "sala": "1",
               "discount_valoric": D("0.00")}]
    vanzari = [{"cod": c * 10, "cod_bon": c, "data": datetime(2026, 8, 5, 12, 0, 0),
                "denumire": "Shaorma demo", "categorie": "Fast-food", "gestiune": "BAR",
                "cantitate": D("1.000"), "pret": D("42.00"), "valoare": D("42.00"),
                "um": "buc", "tva": D("19.00")}]
    return [_serialize(b) for b in bonuri], [_serialize(v) for v in vanzari]


# ─── Backend push (HTTPS outbound) ────────────────────────────────────────────
def _client(cfg: dict) -> "httpx.Client":
    if httpx is None:
        raise RuntimeError("httpx nu e instalat — pip install -r requirements.txt")
    return httpx.Client(timeout=20, headers={"X-POS-Token": cfg["agent_token"]})


def heartbeat(cfg: dict) -> bool:
    body = {
        "queue_pending": queue_len(),
        "dead_letter_count": dead_letter_len(),
        "read_cursor": get_state("read_cursor"),
        "synced_cursor": get_state("synced_cursor"),
        "last_agent_error": get_last_error(),
        "agent_version": AGENT_VERSION,
    }
    try:
        with _client(cfg) as c:
            r = c.post(f"{cfg['backend_url']}/pos/heartbeat", json=body)
        if r.status_code == 200:
            set_state_str("last_heartbeat_ok", _now_str())
            return True
        log.warning("heartbeat HTTP %s", r.status_code)
    except Exception as e:
        log.warning("heartbeat eroare rețea: %s", type(e).__name__)
    return False


def _post_sync(cfg: dict, payload: dict) -> tuple[int, dict]:
    """POST /pos/sync. status 0 = eroare rețea."""
    try:
        with _client(cfg) as c:
            r = c.post(f"{cfg['backend_url']}/pos/sync", json=payload)
        try:
            body = r.json()
        except Exception:
            body = {}
        return r.status_code, body
    except Exception as e:
        log.warning("sync eroare rețea: %s", type(e).__name__)
        return 0, {}


def _backoff_seconds(retry_count: int) -> int:
    return min(BACKOFF_BASE * (2 ** retry_count), BACKOFF_CAP)


# Coduri care se REÎNCEARCĂ (tranzitorii sau auth) — NU se dead-letter-uiesc.
# 401/403 = token respins/revocat (se rezolvă din aplicație) -> așteaptă, nu pierde date.
# 408/425/429 + 0(rețea) + 5xx = tranzitorii.
_RETRYABLE = {0, 401, 403, 408, 425, 429}


def drain_queue(cfg: dict) -> int:
    """
    Golește queue-ul FIFO (doar itemele scadente).
      200                         -> șterge, avansează synced_cursor
      0/401/403/408/425/429/5xx   -> retry cu backoff, RĂMÂNE în queue, STOP
                                     (5xx persistent peste MAX_RETRY -> dead-letter, anti head-of-line)
      alt 4xx (400/413/422...)    -> dead-letter (validare, nu se rezolvă prin retry)
    """
    sent = 0
    while True:
        conn = _db()
        row = conn.execute(
            "SELECT id, payload, max_cod, retry_count FROM queue "
            "WHERE next_attempt_at <= datetime('now') ORDER BY id LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            break
        qid, payload_json, max_cod, retry_count = row
        payload = json.loads(payload_json)

        status, body = _post_sync(cfg, payload)

        if status == 200:
            conn = _db()
            conn.execute("DELETE FROM queue WHERE id=?", (qid,))
            conn.commit(); conn.close()
            if max_cod > get_state("synced_cursor"):
                set_state("synced_cursor", max_cod)
            set_state_str("last_sync_ok", _now_str())
            set_last_error(None)
            sent += 1
            log.info("  -> trimis batch #%s (primite=%s, inserate noi=%s, cursor=%s)",
                     qid, body.get("received_bonuri"), body.get("inserted_bonuri"), max_cod)
            continue

        if status in _RETRYABLE or status >= 500:
            rc = retry_count + 1
            # DOAR 5xx persistent = payload otrăvit -> dead-letter (deblochează coada).
            # 0/401/403/408/425/429 = tranzitorii/auth -> retry la nesfârșit cu backoff.
            if status >= 500 and rc >= MAX_RETRY:
                conn = _db()
                conn.execute("INSERT INTO dead_letter (payload, max_cod, last_error) VALUES (?,?,?)",
                             (payload_json, max_cod, f"HTTP {status} după {rc} retry"))
                conn.execute("DELETE FROM queue WHERE id=?", (qid,))
                conn.commit(); conn.close()
                set_last_error(f"batch #{qid} dead-letter HTTP {status} după {rc} retry")
                log.error("batch #%s -> dead-letter (HTTP %s persistent după %s retry)", qid, status, rc)
                continue
            delay = _backoff_seconds(rc)
            conn = _db()
            conn.execute(
                "UPDATE queue SET retry_count=?, last_error=?, "
                "next_attempt_at=datetime('now', ?) WHERE id=?",
                (rc, f"HTTP {status}", f"+{delay} seconds", qid),
            )
            conn.commit(); conn.close()
            if status in (401, 403):
                set_last_error(f"Cloud a respins tokenul (HTTP {status}). "
                               f"Reconectează codul din aplicație (rulează setup).")
                log.warning("batch #%s: token respins (HTTP %s) — reîncerc; reconectează din aplicație", qid, status)
            else:
                log.warning("batch #%s amânat (HTTP %s, retry %s, +%ss)", qid, status, rc, delay)
            break

        # alt 4xx (validare: 400/413/422...) -> dead-letter
        conn = _db()
        conn.execute("INSERT INTO dead_letter (payload, max_cod, last_error) VALUES (?,?,?)",
                     (payload_json, max_cod, f"HTTP {status}: {str(body.get('detail',''))[:120]}"))
        conn.execute("DELETE FROM queue WHERE id=?", (qid,))
        conn.commit(); conn.close()
        set_last_error(f"batch #{qid} dead-letter HTTP {status} (validare)")
        log.error("batch #%s -> dead-letter (HTTP %s: %s)", qid, status, body.get("detail"))
    return sent


def sync_registru_casa(cfg: dict) -> None:
    """Registrul de casă (fond de casă + Raport Z). Volum mic → push DIRECT
    (fără queue durabilă). Cursorul avansează doar la 200; idempotent pe backend."""
    read_cur = get_state("read_cursor_casa")
    for _ in range(MAX_CATCHUP_ITERS):
        try:
            rows = read_registru_casa(cfg, read_cur)
        except Exception as e:
            log.warning("citire registru_casa eșuată: %s", type(e).__name__)
            return
        if not rows:
            return
        max_cod = max(int(r["cod"]) for r in rows)
        status, body = _post_sync(cfg, {"bonuri": [], "vanzari": [], "registru_casa": rows})
        if status != 200:
            log.warning("registru_casa push HTTP %s — reîncerc data viitoare", status)
            return
        set_state("read_cursor_casa", max_cod)
        log.info("  -> registru_casa: %s rânduri (inserate noi=%s, cursor=%s)",
                 len(rows), body.get("inserted_casa"), max_cod)
        read_cur = max_cod
        if len(rows) < int(cfg["batch_size"]):
            return


# ─── Diagnostic: descoperă tabelul cu mișcările de casă (Depunere/Retragere/Zi) ─
_CASA_KW = ("casa", "numerar", "depuner", "retrager", "inchider", "deschider",
            "registru", "rulaj", "sold", "fond", "_zi", "zilnic", "raport")


def _discover_casa(cfg: dict) -> None:
    """O dată la pornire: listează tabelele UnityPOS + eșantion din cele candidate
    (mișcări de casă) și trimite diagnosticul în cloud (rând special cod=999999999
    în registru_casa) ca să identific tabelul fondului de casă — fără poze."""
    if get_state("diag_casa_sent"):
        return
    try:
        conn = unitypos_connect(cfg)
        try:
            cur = conn.cursor()
            cur.execute("SHOW TABLES")
            tables = [list(r.values())[0] for r in cur.fetchall()]
            cand = {}
            for t in tables:
                if any(k in t.lower() for k in _CASA_KW):
                    try:
                        cur.execute(f"SELECT COUNT(*) AS c FROM `{t}`")
                        n = cur.fetchone()["c"]
                        cur.execute(f"SELECT * FROM `{t}` ORDER BY 1 DESC LIMIT 2")
                        cand[t] = {"n": n, "sample": [_serialize(r) for r in cur.fetchall()]}
                    except Exception as e:
                        cand[t] = {"err": type(e).__name__}
        finally:
            conn.close()
        diag = {"cod": 999999999, "__diag__": True, "tables": tables, "candidates": cand}
        status, _ = _post_sync(cfg, {"bonuri": [], "vanzari": [], "registru_casa": [diag]})
        if status == 200:
            set_state("diag_casa_sent", 1)
            log.info("DIAG casă trimis în cloud (%s tabele, candidați: %s)", len(tables), list(cand.keys()))
        else:
            log.warning("DIAG casă push HTTP %s", status)
    except Exception as e:
        log.warning("DIAG casă eșuat: %s", type(e).__name__)


# ─── Un ciclu de sync (cu catch-up rapid la prima pornire) ───────────────────
def sync_once(cfg: dict, dry_run: bool = False) -> int:
    if dry_run:
        bonuri, vanzari = _synthetic(get_state("read_cursor"))
        log.info("[dry-run] payload (NU se trimite): %s bonuri, %s vânzări", len(bonuri), len(vanzari))
        print(json.dumps({"bonuri": bonuri, "vanzari": vanzari}, indent=2, ensure_ascii=False))
        return 0
    if not cfg["agent_token"]:
        log.error("Lipsește token-ul. Rulează 'horeca-snackyou.exe setup' întâi.")
        return -1

    heartbeat(cfg)
    drain_queue(cfg)  # întâi golește ce a rămas din cicluri anterioare

    total_new = 0
    iterations = 0
    while True:
        read_cur = get_state("read_cursor")
        try:
            bonuri, vanzari = read_unitypos(cfg, read_cur)
            set_last_error(None)
        except Exception as e:
            msg = f"citire UnityPOS eșuată: {type(e).__name__}: {str(e)[:120]}"
            log.error(msg)
            set_last_error(msg)
            return -1

        if not bonuri:
            if iterations == 0:
                log.info("Nimic nou (cursor=%s, în așteptare=%s)", read_cur, queue_len())
            break

        max_cod = max(int(b["cod"]) for b in bonuri)
        enqueue(bonuri, vanzari, max_cod)
        set_state("read_cursor", max_cod)
        total_new += len(bonuri)
        drain_queue(cfg)
        iterations += 1

        if len(bonuri) < int(cfg["batch_size"]):
            break  # ultimul batch parțial -> am ajuns la zi
        if iterations >= MAX_CATCHUP_ITERS:
            log.warning("catch-up oprit la %s batch-uri — continui la ciclul următor", iterations)
            break

    # Registru de casă (fond de casă + Raport Z) — supliment, push direct
    sync_registru_casa(cfg)

    if total_new:
        log.info("Ciclu: %s bonuri noi citite.", total_new)
    dl = dead_letter_len()
    if dl > 0:
        log.warning("ATENȚIE: %s batch-uri în dead-letter — rulează 'status'", dl)
    # Semnal onest pt `sync-once`: dacă au rămas batch-uri NEconfirmate de cloud
    # (token greșit / cloud jos / fără net), NU raportăm succes — exit non-zero.
    pending = queue_len()
    if pending > 0:
        log.warning("%s batch-uri captate local dar NU confirmate de cloud (%s).",
                    pending, get_last_error() or "verifică internetul/token-ul")
        return -1
    return total_new


# ─── Single-instance lock (autostart + dublu-click să nu ruleze 2 agenți) ────
_lock_handle = None  # ținut deschis cât trăiește procesul


def acquire_single_instance() -> bool:
    """True dacă am obținut lock-ul (suntem singurul agent). False dacă rulează deja."""
    global _lock_handle
    lock_path = _DATA_DIR / "horeca-snackyou.lock"
    try:
        _lock_handle = open(lock_path, "w")
        if sys.platform.startswith("win"):
            import msvcrt
            try:
                msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return False
        else:
            import fcntl
            try:
                fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
        return True
    except Exception:
        return True  # dacă mecanismul de lock pică, NU blocăm agentul


def _ensure_autostart() -> None:
    """Self-healing: dacă scurtătura de pornire automată (folder Startup) lipsește,
    o (re)creează. Așa agentul revine singur după o repornire. Best-effort, silent."""
    if not sys.platform.startswith("win"):
        return
    try:
        if not os.path.exists(_startup_lnk_path()):
            cmd_install()
    except Exception:
        pass


def run_loop(cfg: dict, dry_run: bool = False) -> int:
    if not dry_run and not acquire_single_instance():
        print("Agentul rulează deja (altă fereastră). Închid această fereastră.")
        return 0
    if not dry_run:
        _ensure_autostart()
    print("=" * 60)
    print("  HORECA SNACKYOU — casa de marcat conectată la cloud")
    print(f"  cloud:    {cfg['backend_url']}")
    print(f"  UnityPOS: {cfg['unitypos_host']}:{cfg['unitypos_port']}/{cfg['unitypos_database']}")
    print(f"  interval: {cfg['sync_interval_seconds']}s   versiune: {AGENT_VERSION}")
    print("  (lasă fereastra deschisă — se sincronizează singur)")
    print("=" * 60)
    if not dry_run:
        _discover_casa(cfg)
    interval = int(cfg["sync_interval_seconds"])
    while True:
        try:
            sync_once(cfg, dry_run=dry_run)
        except KeyboardInterrupt:
            log.info("Oprit manual."); return 0
        except Exception as e:
            log.error("Iterație eșuată: %s", type(e).__name__)
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            log.info("Oprit manual."); return 0


# ─── register ─────────────────────────────────────────────────────────────────
def register(cfg: dict, pairing_code: str) -> tuple[str | None, str]:
    """Consumă pairing code. Returnează (token|None, motiv).
    motiv: 'ok' | 'network' (fără internet/cloud) | 'invalid' (cod greșit) | 'error'."""
    if httpx is None:
        log.error("httpx lipsește.")
        return None, "error"
    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(f"{cfg['backend_url']}/pos/register", json={"pairing_code": pairing_code.strip()})
    except Exception as e:
        log.error("Nu pot contacta cloud-ul: %s", type(e).__name__)
        return None, "network"
    if r.status_code == 200:
        return r.json()["agent_token"], "ok"
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text[:150]
    log.error("Înregistrare eșuată (HTTP %s): %s", r.status_code, detail)
    # 4xx = cod invalid/expirat; 5xx/altele = problemă temporară de server.
    return None, "invalid" if 400 <= r.status_code < 500 else "network"


# ─── setup ghidat ─────────────────────────────────────────────────────────────
def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        raise _SetupAborted()  # fără stdin interactiv -> abandon, nu buclă infinită
    return val or default


def _yes(val: str) -> bool:
    return val.strip().lower() in ("da", "d", "y", "yes")


def _setup_flow(cfg: dict) -> int:
    print("\n" + "=" * 60)
    print("  CONFIGURARE HORECA SNACKYOU (o singură dată)")
    print("=" * 60)

    # 1) Conexiune la UnityPOS local
    print("\n[1/3] Conectare la casa de marcat (UnityPOS local)")
    candidates = []
    if cfg["unitypos_password"]:
        candidates.append(cfg["unitypos_password"])
    candidates += ["matricx", ""]
    ok = False
    for pw in candidates:
        cfg["unitypos_password"] = pw
        ok, ver, err = test_unitypos(cfg)
        if ok:
            shown = "(goală)" if pw == "" else "•" * len(pw)
            print(f"  ✓ Conectat la UnityPOS (MySQL {ver}). Parolă folosită: {shown}")
            break
    while not ok:
        print("  ✗ Nu m-am putut conecta cu parolele uzuale.")
        print("    Am nevoie de parola bazei de date MySQL de pe ACEST PC")
        print("    (parola pe care o folosește UnityPOS — root@localhost).")
        pw = _ask("  Parola MySQL (Enter = parolă goală)")
        cfg["unitypos_password"] = pw
        cfg["unitypos_host"] = _ask("  Host UnityPOS", cfg["unitypos_host"])
        cfg["unitypos_database"] = _ask("  Baza de date", cfg["unitypos_database"])
        ok, ver, err = test_unitypos(cfg)
        if ok:
            print(f"  ✓ Conectat la UnityPOS (MySQL {ver}).")
        else:
            print(f"  ✗ Tot nu merge: {err}")
            if not _yes(_ask("  Reîncerc? (da/nu)", "da")):
                print("  Renunț la configurare. Rulează din nou când ai parola.")
                return 1

    # 2) Conectare la cloud (pairing code)
    print("\n[2/3] Conectare la contul din cloud")
    if cfg["agent_token"]:
        if not _yes(_ask("  Există deja un token salvat. Îl păstrez? (da/nu)", "da")):
            cfg["agent_token"] = ""
    if not cfg["agent_token"]:
        print("  Din aplicație (Setări -> Conexiune POS) apasă „Generează cod de")
        print("  conectare” și copiază codul (forma SNK-XXXX-XXXX).")
        while not cfg["agent_token"]:
            code = _ask("  Cod de conectare (SNK-XXXX-XXXX)")
            if not code:
                print("  Fără cod nu pot continua.")
                if _yes(_ask("  Renunț? (da/nu)", "nu")):
                    return 1
                continue
            token, reason = register(cfg, code)
            if token:
                cfg["agent_token"] = token
                print("  ✓ Conectat la cloud. Token salvat.")
            elif reason == "network":
                print("  ✗ Nu am internet / nu pot contacta cloud-ul. Verifică conexiunea")
                print("    la internet și încearcă din nou (codul e încă valid ~30 min,")
                print("    NU trebuie să generezi altul dacă reîncerci repede).")
            else:
                print("  ✗ Cod invalid/expirat. Generează altul în aplicație și încearcă din nou.")

    save_config(cfg)

    # 3) Pornire automată
    print("\n[3/3] Pornire automată cu Windows")
    if sys.platform.startswith("win"):
        if _yes(_ask("  Pornesc automat agentul la fiecare pornire a PC-ului? (da/nu)", "da")):
            if cmd_install() != 0:
                print("  ! Nu am putut activa pornirea automată acum. Agentul MERGE în")
                print("    continuare, dar după o repornire a PC-ului trebuie pornit manual")
                print("    (dublu-click pe horeca-snackyou.exe). Ca să se activeze automat:")
                print("    click-dreapta pe exe -> „Run as administrator”, apoi rulează încă o dată setup.")
    else:
        print("  (pas disponibil doar pe Windows — sar peste)")

    print("\n" + "=" * 60)
    print("  GATA. Pornesc sincronizarea acum.")
    print("=" * 60 + "\n")
    return run_loop(cfg)


def cmd_setup(cfg: dict) -> int:
    try:
        return _setup_flow(cfg)
    except _SetupAborted:
        print("\nConfigurare întreruptă. Rulează din nou 'setup' când ești gata.")
        return 1


# ─── status ───────────────────────────────────────────────────────────────────
def cmd_status(cfg: dict) -> int:
    print("— HORECA SNACKYOU — stare —")
    print(f"  config:        {CONFIG_PATH}")
    print(f"  cloud:         {cfg['backend_url']}")
    print(f"  token:         {'setat' if cfg['agent_token'] else 'LIPSĂ (rulează setup)'}")
    print(f"  UnityPOS:      {cfg['unitypos_host']}:{cfg['unitypos_port']}/{cfg['unitypos_database']}")
    ok, ver, err = test_unitypos(cfg)
    print(f"  UnityPOS test: {'OK (MySQL ' + str(ver) + ')' if ok else 'EȘUAT: ' + str(err)}")
    if cfg["agent_token"]:
        cloud_ok = heartbeat(cfg)
        print(f"  Cloud test:    {'OK (răspunde)' if cloud_ok else 'NU răspunde / token respins'}")
    print(f"  ultimul sync:  {get_state_str('last_sync_ok') or '— (încă niciunul)'}")
    print(f"  read_cursor:   {get_state('read_cursor')}")
    print(f"  synced_cursor: {get_state('synced_cursor')}")
    print(f"  în așteptare:  {queue_len()}")
    dl = dead_letter_len()
    print(f"  dead-letter:   {dl}")
    if dl > 0:
        print("    ! Unele bonuri au fost respinse definitiv. Reconectează codul din")
        print("      aplicație (rulează setup) sau sună la suport.")
    le = get_last_error()
    if le:
        print(f"  ultima eroare: {le}")
    return 0


# ─── install / uninstall (folder Startup — FĂRĂ admin, FĂRĂ schtasks) ─────────
# schtasks e blocat pe unele case (POS): „Access is denied". Scurtătura din
# folderul Startup al utilizatorului rulează la fiecare login fără drepturi speciale.
def _startup_lnk_path() -> str:
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup", "HorecaSnackYou.lnk")


def cmd_install() -> int:
    if not sys.platform.startswith("win"):
        print("Pornirea automată e disponibilă doar pe Windows.")
        return 1
    exe = sys.executable
    args = "run" if getattr(sys, "frozen", False) else f'"{Path(__file__).resolve()}" run'
    lnk = _startup_lnk_path()
    ps = (
        "$W=New-Object -ComObject WScript.Shell;"
        f"$S=$W.CreateShortcut('{lnk}');"
        f"$S.TargetPath='{exe}';"
        f"$S.Arguments='{args}';"
        f"$S.WorkingDirectory='{os.path.dirname(exe)}';"
        "$S.Save()"
    )
    try:
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       check=True, capture_output=True, text=True)
        print("  ✓ Pornire automată activată (scurtătură în folderul Startup).")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"  ✗ Nu am putut crea scurtătura: {(e.stderr or e.stdout or '').strip()[:150]}")
        return 1
    except FileNotFoundError:
        print("  ✗ powershell indisponibil.")
        return 1


def cmd_uninstall() -> int:
    if not sys.platform.startswith("win"):
        print("Disponibil doar pe Windows.")
        return 1
    try:
        lnk = _startup_lnk_path()
        if os.path.exists(lnk):
            os.remove(lnk)
        print("  ✓ Pornire automată dezactivată.")
        return 0
    except Exception as e:
        print(f"  ✗ {type(e).__name__}")
        return 1


# ─── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(prog="horeca-snackyou", description="Agent casă de marcat SnackYou")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("setup", help="configurare ghidată (o singură dată)")
    rr = sub.add_parser("run", help="pornește sync-ul continuu")
    rr.add_argument("--dry-run", action="store_true")
    so = sub.add_parser("sync-once", help="o singură iterație")
    so.add_argument("--dry-run", action="store_true")
    reg = sub.add_parser("register", help="înregistrează cu pairing code")
    reg.add_argument("pairing_code")
    sub.add_parser("status", help="stare locală")
    sub.add_parser("install", help="pornire automată cu Windows")
    sub.add_parser("uninstall", help="dezactivează pornirea automată")
    args = p.parse_args()

    cfg = load_config()

    # Fără argument (dublu-click pe .exe): setup dacă nu e gata, altfel run.
    if args.cmd is None:
        if cfg["agent_token"]:
            return run_loop(cfg)
        return cmd_setup(cfg)

    if args.cmd == "setup":
        return cmd_setup(cfg)
    if args.cmd == "run":
        return run_loop(cfg, dry_run=args.dry_run)
    if args.cmd == "sync-once":
        return 0 if sync_once(cfg, dry_run=args.dry_run) >= 0 else 1
    if args.cmd == "register":
        token, reason = register(cfg, args.pairing_code)
        if token:
            cfg["agent_token"] = token
            save_config(cfg)
            print("✓ Token salvat.")
            return 0
        print("✗ " + ("Nu pot contacta cloud-ul (verifică internetul)."
                       if reason == "network" else "Cod invalid/expirat."))
        return 1
    if args.cmd == "status":
        return cmd_status(cfg)
    if args.cmd == "install":
        return cmd_install()
    if args.cmd == "uninstall":
        return cmd_uninstall()
    return 1


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    except KeyboardInterrupt:
        rc = 0
    except Exception:
        import traceback
        traceback.print_exc()
        rc = 1
    # Dublu-click pe .exe care iese cu eroare: ține fereastra deschisă ca omul să
    # apuce să citească (altfel se închide instant). La 'run' nu se ajunge aici (buclă).
    if getattr(sys, "frozen", False) and rc not in (0, None):
        try:
            input("\nApasă Enter ca să închizi fereastra...")
        except Exception:
            pass
    sys.exit(rc or 0)
