"""Bounded, read-only daily PDF samples, independent of receipt synchronization."""
import base64
import hashlib
import os
import re
import stat
import time
from datetime import date
from pathlib import Path

MAX_FILE_BYTES = 64 * 1024
MAX_SAMPLES = 2
NAME = re.compile(r'raport_zilnic-\d+-(\d{4}-\d{2}-\d{2})\.pdf$', re.I)


def regular_path(path):
    # Reject reparse points on every ancestor before opening anything.
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
            return False
    return True


def collect_archive_samples(roots, now=None):
    now = time.time() if now is None else now
    archives, candidates, seen = [], [], set()
    for root in roots:
        root = Path(root).absolute()
        folder = root if root.name.lower() == 'rapoarte_zilnice' else root / 'rapoarte_zilnice'
        try:
            if not regular_path(folder) or not folder.is_dir():
                continue
            key = os.path.normcase(str(folder))
            if key in seen:
                continue
            seen.add(key)
            summary = {'location': str(folder), 'matched_files': 0, 'truncated': False, 'errors': 0}
            archives.append(summary)
            start = time.monotonic()
            with os.scandir(folder) as entries:
                for i, entry in enumerate(entries):
                    if i >= 10000 or time.monotonic() - start > 3:
                        summary['truncated'] = True
                        break
                    match = NAME.fullmatch(entry.name)
                    if not match:
                        continue
                    try:
                        day = date.fromisoformat(match[1]).isoformat()
                        # Windows DirEntry.stat caches zero file identifiers; use a fresh
                        # path stat so identity can be compared with the open handle.
                        info = os.stat(entry.path, follow_symlinks=False)
                        if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                            continue
                        summary['matched_files'] += 1
                        candidates.append((day, info.st_mtime, Path(entry.path), info))
                    except (ValueError, OSError):
                        summary['errors'] += 1
        except OSError:
            continue
    samples, skipped = [], []
    for day, modified, path, before in sorted(candidates, key=lambda x: (x[0], x[1], str(x[2])), reverse=True)[:20]:
        if len(samples) >= MAX_SAMPLES:
            break
        item = {'name': path.name, 'archive': str(path.parent), 'date': day}
        reason = None
        try:
            if now - modified < 60:
                reason = 'still_recent'
            elif before.st_size > MAX_FILE_BYTES:
                reason = 'too_large'
            elif not regular_path(path):
                reason = 'unsafe_path'
            else:
                with path.open('rb') as stream:
                    opened = os.fstat(stream.fileno())
                    data = stream.read(MAX_FILE_BYTES + 1)
                    after = os.fstat(stream.fileno())
                signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
                if signature(before) != signature(opened) or signature(opened) != signature(after) or len(data) != before.st_size:
                    reason = 'changed_during_read'
                elif not data.startswith(b'%PDF-'):
                    reason = 'not_pdf'
                else:
                    samples.append(dict(item, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                        content_base64=base64.b64encode(data).decode('ascii')))
        except OSError:
            reason = 'unreadable'
        if reason and len(skipped) < 20:
            skipped.append(dict(item, reason=reason))
    return {'archives': archives, 'samples': samples, 'skipped': skipped,
            'fiscal_source_verified': False, 'sample_limit': MAX_SAMPLES, 'inspection_limit': 20,
            'selection_limited': len(candidates) > 20}
