"""Standalone schema/file metadata diagnostic; never import the running agent."""
import json
import os
import stat
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path
from archive_samples import collect_archive_samples
from fiscal_discovery import collect_fiscal_sources
from targeted_z import sample_reports, report_excerpt
from pos_discovery import installed_pos_folders
from disk_discovery import disk_candidates, xml_path_hints

SCHEMA_SQL = """SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_KEY
FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s
ORDER BY TABLE_NAME, ORDINAL_POSITION LIMIT 10001"""
MARKERS = ('raport', 'fiscal', 'inchid', 'registru', 'nr_z', 'numar_z', 'zreport', 'z_report', 'rapz')


def candidate(name):
    name = name.lower()
    return name == 'z' or any(word in name for word in MARKERS)


def safe_error(exc):
    # Exception messages can contain hostnames, credentials or SQL literals.
    code = exc.args[0] if exc.args and type(exc.args[0]) is int else None
    return {'error_type': type(exc).__name__, 'mysql_code': code}


def database_report(config, connect=None):
    if connect is None:
        import pymysql
        connect = pymysql.connect
    conn = None
    try:
        database = config['unitypos_database']
        if not isinstance(database, str) or not database:
            raise ValueError('missing database')
        conn = connect(host=config['unitypos_host'], port=int(config.get('unitypos_port', 3306)),
                       user=config['unitypos_user'], password=config.get('unitypos_password', ''),
                       database=database, charset='utf8mb4', connect_timeout=5,
                       read_timeout=8, write_timeout=8, autocommit=True,
                       local_infile=False)
        with conn.cursor() as cursor:
            cursor.execute(SCHEMA_SQL, (database,))
            rows = cursor.fetchall()
        tables = {}
        for table, column, dtype, key in rows[:10000]:
            entry = tables.setdefault(table, {'name': table, 'candidate_z': candidate(table), 'columns': []})
            entry['columns'].append({'name': column, 'type': dtype, 'key': key})
            entry['candidate_z'] |= candidate(column)
        samples = sample_reports(conn, tables)
        return {'status': 'ok', 'truncated': len(rows) > 10000,
                'tables': list(tables.values()), 'targeted_samples': samples,
                'business_rows_read': sum(len(v.get('rows', [])) for v in samples.values())}
    except Exception as exc:
        return {'status': 'error', **safe_error(exc)}
    finally:
        if conn is not None:
            conn.close()


def file_report(folder):
    """Bounded metadata only; no contents, symlinks or Windows junctions."""
    root = Path(folder).resolve()
    if root == Path(root.anchor) or root == Path.home().resolve() or not root.is_dir():
        return {'status': 'invalid_folder', 'files': []}
    start = time.monotonic()
    pending = [(root, 0)]
    files, examined, errors = [], 0, 0
    truncated = False
    excerpt_count = 0
    while pending:
        directory, depth = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    examined += 1
                    if examined > 5000 or len(files) >= 200 or time.monotonic() - start > 10:
                        truncated = True
                        return {'status': 'ok', 'truncated': truncated, 'errors': errors, 'files': files}
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if entry.is_symlink() or getattr(info, 'st_file_attributes', 0) & 1024:
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if depth < 4 and entry.name.lower() not in ('node_modules', '.git', 'windows'):
                                pending.append((Path(entry.path), depth + 1))
                            else:
                                truncated = True
                            continue
                        name = entry.name.lower()
                        if any(word in name for word in ('password', 'secret', 'token', 'config', '.env', 'state')):
                            continue
                        if candidate(name) or Path(name).suffix in ('.fdb', '.mdb', '.dbf', '.sqlite', '.db', '.pdf', '.xml'):
                            item = {'path_relative_to_pos': str(Path(entry.path).relative_to(root)),
                                    'bytes': info.st_size, 'modified_epoch': info.st_mtime}
                            if excerpt_count < 5:
                                excerpt = report_excerpt(Path(entry.path))
                                if excerpt:
                                    item['z_text_candidate'] = excerpt
                                    excerpt_count += 1
                            files.append(item)
                    except OSError:
                        errors += 1
        except OSError:
            errors += 1
    return {'status': 'ok', 'truncated': truncated, 'errors': errors, 'files': files}


def clean_path(value):
    return Path(value.strip().strip('"'))


def app_dir():
    return Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent


def running_paths():
    if os.name != 'nt':
        return []
    # Query executable paths only, never process command lines (may contain secrets).
    script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; @(Get-CimInstance Win32_Process -Filter \"Name='horeca-snackyou.exe' OR Name LIKE '%UnityPOS%'\" | Select-Object -ExpandProperty ExecutablePath) | ConvertTo-Json -Compress"
    try:
        ps = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        result = subprocess.run([str(ps), '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, timeout=10, encoding='utf-8', errors='replace')
        data = json.loads(result.stdout.strip().lstrip('\ufeff') or '[]')
        if isinstance(data, str): data = [data]
        return [Path(p) for p in data if isinstance(p, str) and p][:20]
    except Exception:
        return []


def discover_configs(processes):
    folders = [app_dir()]
    folders += [p.parent for p in processes if p.name.lower() == 'horeca-snackyou.exe']
    for key in ('LOCALAPPDATA', 'APPDATA'):
        if os.environ.get(key): folders.append(Path(os.environ[key]) / 'HorecaSnackYou')
    choices = []
    for folder in folders:
        path = folder / 'horeca-snackyou.config.json'
        if path.is_file() and path.resolve() not in choices:
            choices.append(path.resolve())
    return choices


def choose_config():
    choices = discover_configs(running_paths())
    if len(choices) == 1:
        print('Configuratia agentului a fost gasita automat.')
        return choices[0]
    if not choices:
        print('Configuratia nu a fost gasita automat. Raportul va marca acest lucru.')
        return None
    for i, path in enumerate(choices, 1):
        print(f'{i}. {path}')
    value = input('Mai multe configuratii: alege numarul sau Enter pentru a sari: ').strip()
    if value.isdigit() and 1 <= int(value) <= len(choices):
        return choices[int(value) - 1]
    return None


def discover_pos():
    folders = [p.parent for p in running_paths() if 'unitypos' in p.name.lower()]
    folders += installed_pos_folders()
    folders += disk_candidates()
    for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if os.environ.get(key): folders.append(Path(os.environ[key]) / 'UnityPOS')
    if os.name == 'nt': folders.append(Path('C:/UnityPOS'))
    roots = list(dict.fromkeys(p.resolve() for p in folders if p.is_dir()))[:8]
    for root in list(roots):
        hints, _ = xml_path_hints(root)
        roots.extend(hints)
    return list(dict.fromkeys(roots))[:12]


def collect_report(config):
    report = {'version': '1.5-cloud', 'created_at': datetime.now().astimezone().isoformat(),
              'fiscal_source_verified': False, 'database': database_report(config)}
    try:
        folders = discover_pos()
        report['daily_archive'] = collect_archive_samples(folders)
        try:
            report['fiscal_discovery'] = collect_fiscal_sources(folders)
        except Exception as exc:
            report['fiscal_discovery'] = {'status': 'error', **safe_error(exc)}
        report['filesystem'] = {'status': 'ok' if folders else 'pos_folder_not_found',
            'folders': [dict(label='POS-'+str(i+1), location=str(p), config_structure=xml_path_hints(p)[1], **file_report(p)) for i,p in enumerate(folders)]}
    except Exception as exc:
        report['filesystem'] = {'status': 'error', **safe_error(exc)}
    return report


def main():
    print('SnackYou - diagnostic Z separat. Lasa agentul si UnityPOS pornite.')
    print('Doar citire: inregistrari registru/inchidere si documente Z candidate.')
    report = {'version': '1.5-cloud', 'created_at': datetime.now().astimezone().isoformat(),
              'fiscal_source_verified': False, 'database': {'status': 'skipped'},
              'filesystem': {'status': 'skipped'}}
    try:
        path = choose_config()
        if path is not None:
            if path.stat().st_size > 1024 * 1024:
                raise ValueError('config too large')
            config = json.loads(path.read_text(encoding='utf-8-sig'))
            print('Citesc structura bazei, printr-o conexiune separata...')
            report['database'] = database_report(config)
            del config
        else:
            report['database'] = {'status': 'config_not_selected_or_not_found'}
    except Exception as exc:
        report['database'] = {'status': 'config_error', **safe_error(exc)}
    try:
        folders = discover_pos()
        report['daily_archive'] = collect_archive_samples(folders)
        try:
            report['fiscal_discovery'] = collect_fiscal_sources(folders)
        except Exception as exc:
            report['fiscal_discovery'] = {'status': 'error', **safe_error(exc)}
        report['filesystem'] = {'status': 'ok' if folders else 'pos_folder_not_found',
                                'folders': [dict(label='POS-' + str(i+1), **file_report(p)) for i, p in enumerate(folders)]}
    except Exception as exc:
        report['filesystem'] = {'status': 'error', **safe_error(exc)}
    output = app_dir() / ('diagnostic-z-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Raport salvat: ' + str(output))
    print('Baza: ' + report['database']['status'] + '; fisiere: ' + report['filesystem']['status'])
    print('Trimite doar fisierul diagnostic-z-....json, inclusiv daca arata error.')
    print('Nu trimite configuratia agentului. Agentul nu a fost oprit sau modificat.')
    if os.name == 'nt' and '--no-open' not in sys.argv:
        subprocess.Popen([str(Path(os.environ['SystemRoot']) / 'explorer.exe'), '/select,', str(output)])


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\nDiagnostic anulat. Agentul nu a fost modificat.')
        sys.exit(2)
    except Exception as exc:
        print('Nu pot salva diagnosticul: ' + type(exc).__name__)
        print('Extrage pachetul pe Desktop intr-un folder separat si reincearca.')
        sys.exit(1)
