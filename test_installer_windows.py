"""Real silent installer upgrade test on Windows; synthetic files only."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing


@unittest.skipUnless(os.name == 'nt', 'Requires Windows and compiled Inno Setup installer')
class InstallerUpgradeTests(unittest.TestCase):
    def test_upgrade_preserves_config_database_and_pending_files(self):
        installer = Path('installer_out/horeca-snackyou-setup.exe').resolve()
        self.assertTrue(installer.is_file())
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'HorecaSnackYou'
            args = [str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/DIR=' + str(target)]
            subprocess.run(args, check=True, timeout=120)
            self.assertTrue((target / 'snackyou-diagnostic.exe').is_file())
            config = target / 'horeca-snackyou.config.json'
            config.write_text('{"agent_token":"SYNTHETIC-NOT-A-REAL-TOKEN","unitypos_database":"fixture"}')
            db = target / 'horeca-snackyou.state.db'
            with closing(sqlite3.connect(db)) as conn:
                conn.execute('CREATE TABLE fixture (cursor INTEGER, queued TEXT)')
                conn.execute('INSERT INTO fixture VALUES (15213, ?)', ('synthetic pending receipt',))
                conn.commit()
            pending = target / 'custom-pending.txt'
            pending.write_text('synthetic untouched')
            outbox = target / 'horeca-diagnostic-outbox.json'
            outbox.write_text('{"last_sent": 100, "collector_version": 1}')
            files = (config, db, pending, outbox)
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            try:
                subprocess.run(args, check=True, timeout=120)
                self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
                self.assertTrue((target / 'horeca-snackyou.exe').is_file())
                archive = Path(tmp) / 'UnityPOS' / 'rapoarte_zilnice'
                archive.mkdir(parents=True)
                pdf = archive / 'raport_zilnic-1-2026-10-19.pdf'
                pdf.write_bytes(b'%PDF-1.4\nSYNTHETIC WINDOWS FIXTURE')
                os.utime(pdf, (100, 100))
                env = dict(os.environ, LOCALAPPDATA=tmp)
                subprocess.run([str(target / 'snackyou-diagnostic.exe'), '--no-open'], input='\n', text=True, check=True, timeout=120, env=env)
                report = json.loads(next(target.glob('diagnostic-z-*.json')).read_text(encoding='utf-8'))
                self.assertEqual(report['version'], '1.4-cloud')
                self.assertFalse(report['fiscal_source_verified'])
                self.assertEqual(report['daily_archive']['samples'][0]['sha256'], hashlib.sha256(pdf.read_bytes()).hexdigest())
                self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
            finally:
                # Remove only this test installation / runner shortcuts.
                subprocess.run([str(target / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], check=True, timeout=120)
            self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


if __name__ == '__main__': unittest.main()
