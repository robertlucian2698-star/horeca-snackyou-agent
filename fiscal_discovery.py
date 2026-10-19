"""Read-only UnityPrinter configuration hints and fiscal text candidates."""
import os
import re
import stat
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from archive_samples import regular_path
from targeted_z import redact

FIELDS = {'cm', 'driver', 'com', 'baudrate', 'driver_path', 'bf_path', 'bf_name', 'bf_answer', 'printer_path'}
PATH_FIELDS = {'driver_path', 'bf_path', 'bf_answer', 'printer_path'}
TEXT = {'.txt', '.log', '.csv', '.xml', '.jrn'}
EXTENSIONS = TEXT | {'.exe', '.dll', '.pdf', '.dat', '.ini'}
SECRET = re.compile(r'password|passwd|parola|token|secret|credential|api[_-]?key|connectionstring', re.I)
MARKER = re.compile(r'raport\s+fiscal\s+zilnic|\bZ\s*(?:NR\.?|NUMAR)\s*[:=]?\s*\d+|\braport\s+Z\b|<raportz\b', re.I)


def allowed_path(path):
    path = Path(path).absolute()
    if str(path).startswith(('\\\\', '//')) or path == Path(path.anchor) or path == Path.home().absolute():
        return False
    return regular_path(path)


def config_hints(folder):
    config = folder / 'data.xml'
    if not allowed_path(config) or config.stat().st_size > 65536:
        return {}, []
    with config.open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        return {}, []
    root = ET.fromstring(raw)
    fields, paths = {}, []
    for element in root.iter():
        key = element.tag.lower()
        value = (element.text or '').strip()
        if key not in FIELDS or not value or len(value) > 512 or SECRET.search(value) or '://' in value or '@' in value:
            continue
        # Individual field values only, never the full config or attributes.
        if key in PATH_FIELDS:
            if value.startswith(('\\\\', '//')):
                continue
            path = Path(value)
            if not path.is_absolute():
                path = folder / path
            try:
                if allowed_path(path):
                    directory = path if path.is_dir() else path.parent
                    if allowed_path(directory):
                        paths.append(directory)
                        fields[key] = str(path)
            except OSError:
                fields[key] = '[unavailable]'
        elif re.fullmatch(r'[\w .:\\/-]{1,100}', value):
            fields[key] = value
    return fields, paths


def collect_fiscal_sources(roots):
    result = {'configs': [], 'locations': [], 'text_candidates': [], 'errors': [],
              'fiscal_source_verified': False, 'files_inspected': 0}
    folders, seen = [], set()
    for root in roots[:12]:
        root = Path(root).absolute()
        candidates = [root] if root.name.lower() == 'unityprinter' else [root/'printer'/'UnityPrinter', root/'UnityPrinter']
        for folder in candidates:
            if str(folder).lower() in seen:
                continue
            seen.add(str(folder).lower())
            try:
                if not allowed_path(folder) or not folder.is_dir():
                    continue
                folders.append(folder)
                fields, paths = config_hints(folder)
                result['configs'].append({'location': str(folder), 'fields': fields})
                folders.extend(paths)
            except (OSError, ValueError, ET.ParseError) as exc:
                result['errors'].append({'stage': 'config', 'type': type(exc).__name__})
    files = {}
    for folder in list(dict.fromkeys(folders))[:6]:
        summary = {'location': str(folder), 'files': [], 'truncated': False, 'errors': 0}
        result['locations'].append(summary)
        stack, examined, start = [(folder, 0)], 0, time.monotonic()
        while stack:
            directory, depth = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        examined += 1
                        if examined > 2000 or time.monotonic()-start > 3:
                            summary['truncated'] = True
                            stack.clear()
                            break
                        try:
                            info = os.stat(entry.path, follow_symlinks=False)
                            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                                continue
                            path = Path(entry.path)
                            if stat.S_ISDIR(info.st_mode):
                                if depth < 2 and entry.name.lower() not in ('node_modules', '.git', 'users', 'windows'):
                                    stack.append((path, depth+1))
                                continue
                            if not stat.S_ISREG(info.st_mode) or SECRET.search(entry.name) or path.suffix.lower() not in EXTENSIONS:
                                continue
                            metadata = {'path': str(path), 'bytes': info.st_size, 'modified_epoch': info.st_mtime}
                            summary['files'].append(metadata)
                            summary['files'].sort(key=lambda m: m['modified_epoch'], reverse=True)
                            if len(summary['files']) > 80:
                                summary['files'].pop(); summary['truncated'] = True
                            if path.suffix.lower() in TEXT and not re.search(r'config|settings|^data\.xml$',entry.name,re.I):
                                files[str(path)] = (path, info)
                        except OSError:
                            summary['errors'] += 1
            except OSError:
                summary['errors'] += 1
    result['text_scan_limited'] = len(files) > 20
    for path, before in sorted(files.values(),key=lambda pair:pair[1].st_mtime, reverse=True)[:20]:
        if len(result['text_candidates']) >= 3:
            break
        try:
            if not allowed_path(path):
                continue
            with path.open('rb') as stream:
                opened = os.fstat(stream.fileno())
                head = stream.read(16384)
                tail = b''
                if before.st_size > 16384:
                    stream.seek(max(16384,before.st_size-16384))
                    tail = stream.read(16384)
                after = os.fstat(stream.fileno())
            identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
            if identity(before) != identity(opened) or identity(opened) != identity(after):
                continue
            result['files_inspected'] += 1
            for raw, offset in [(head,0), (tail,max(16384,before.st_size-16384))]:
                if not raw or b'\x00' in raw:
                    continue
                try: text = raw.decode('utf-8-sig')
                except UnicodeDecodeError: text = raw.decode('cp1250', errors='replace')
                match = MARKER.search(text)
                if not match:
                    continue
                begin = max(0, match.start()-100)
                preview = redact(text[begin:begin+2048])
                # Also redact simple XML credential values in candidate fragments.
                preview = re.sub(r'(?is)(<(?:password|parola|token|secret)[^>]*>).*?(</[^>]+>)',r'\1[REDACTED]\2',preview)
                result['text_candidates'].append({'path':str(path), 'read_offset_bytes':offset,
                    'preview':preview, 'file_bytes':before.st_size, 'partial':True})
                break
        except OSError as exc:
            result['errors'].append({'stage':'text','type':type(exc).__name__})
    return result
