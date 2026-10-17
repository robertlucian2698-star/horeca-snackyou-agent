"""Real silent installer upgrade test on Windows; synthetic files only."""
import hashlib
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
            files = (config, db, pending)
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            try:
                subprocess.run(args, check=True, timeout=120)
                self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
                self.assertTrue((target / 'horeca-snackyou.exe').is_file())
            finally:
                # Remove only this test installation / runner shortcuts.
                subprocess.run([str(target / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], check=True, timeout=120)
            self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


if __name__ == '__main__': unittest.main()
