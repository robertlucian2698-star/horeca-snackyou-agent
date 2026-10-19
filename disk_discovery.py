"""Bounded discovery on local fixed drives. No writes, credentials or personal docs."""
import os
import stat
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def fixed_roots():
    if os.name != 'nt': return []
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [Path(chr(65+i)+':/') for i in range(26)
            if mask & (1 << i) and ctypes.windll.kernel32.GetDriveTypeW(chr(65+i)+':\\') == 3]


def disk_candidates(roots=None):
    pending = [(p,0) for p in (fixed_roots() if roots is None else roots)]
    found, seen, started = [], 0, time.monotonic()
    skip = {'windows','users','$recycle.bin','system volume information','recovery','.git','node_modules'}
    while pending and seen < 3000 and time.monotonic()-started < 15:
        folder, depth = pending.pop(0)
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    seen += 1
                    if seen > 3000 or time.monotonic()-started >= 15: break
                    info = entry.stat(follow_symlinks=False)
                    if entry.is_symlink() or getattr(info,'st_file_attributes',0)&1024: continue
                    name = entry.name.lower()
                    if stat.S_ISDIR(info.st_mode):
                        if name in skip: continue
                        if 'unity' in name or name in ('pos','unitypos','xampp','wamp','wamp64'):
                            found.append(Path(entry.path))
                        if depth < 2: pending.append((Path(entry.path),depth+1))
                    elif 'unity' in name and name.endswith('.exe'):
                        found.append(Path(entry.path).parent)
        except OSError: continue
    return list(dict.fromkeys(found))[:12]


def xml_path_hints(folder):
    """Read only schema/path fields of small known config files, never values wholesale."""
    paths, structures = [], []
    for name in ('data.xml','config.xml','settings.xml','UnityPOS.config'):
        p = Path(folder)/name
        try:
            if not p.is_file() or p.is_symlink() or p.stat().st_size > 65536: continue
            raw = p.read_bytes()
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper(): continue
            root = ET.fromstring(raw)
            structures.append({'file': name, 'tags': list(dict.fromkeys(e.tag for e in root.iter()))[:40]})
            for e in root.iter():
                for key,value in [(e.tag,e.text or ''), *e.attrib.items()]:
                    key=key.lower()
                    if any(word in key for word in ('pass','token','secret','credential')): continue
                    if not any(word in key for word in ('path','folder','directory','cale','director')): continue
                    candidate=Path(value.strip())
                    if not candidate.is_absolute(): candidate=Path(folder)/candidate
                    if candidate.is_dir() and candidate.resolve()!=Path(candidate.anchor) and candidate.resolve()!=Path.home().resolve():
                        paths.append(candidate.resolve())
        except (OSError, ValueError, ET.ParseError): continue
    return list(dict.fromkeys(paths))[:6], structures
