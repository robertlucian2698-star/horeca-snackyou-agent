import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import diagnostic as d
from install_diagnostic import install


class DiagnosticTests(unittest.TestCase):
    def test_installer_preserves_agent_and_installs_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, local = root / 'source', root / 'local'
            for name in ('runtime/python.exe', 'lib/pymysql/__init__.py', 'diagnostic.py', 'targeted_z.py', 'pos_discovery.py', 'disk_discovery.py'):
                p = source / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('synthetic')
            agent = local / 'HorecaSnackYou'
            agent.mkdir(parents=True)
            for name in ('horeca-snackyou.exe', 'horeca-snackyou.config.json', 'horeca-snackyou.state.db'):
                (agent / name).write_text('DO-NOT-CHANGE')
            target = install(source, local)
            again = install(source, local)
            self.assertNotEqual(target, again)
            self.assertEqual(target.parent.name, 'SnackYouDiagnostic')
            self.assertTrue((target / 'runtime/python.exe').is_file())
            self.assertTrue(all(p.read_text() == 'DO-NOT-CHANGE' for p in agent.iterdir()))

    def test_autodetect_uses_standard_and_process_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            standard = root / 'HorecaSnackYou'
            standard.mkdir()
            config = standard / 'horeca-snackyou.config.json'
            config.write_text('{}')
            with patch.dict('os.environ', {'LOCALAPPDATA': str(root), 'APPDATA': str(root)}), \
                 patch.object(d, 'app_dir', return_value=root), \
                 patch.object(d, 'running_paths', return_value=[standard / 'horeca-snackyou.exe']), \
                 patch('builtins.input', side_effect=AssertionError('must be automatic')):
                self.assertEqual(d.choose_config(), config.resolve())

    def test_multiple_configs_not_silently_selected(self):
        with patch.object(d, 'discover_configs', return_value=[Path('a'), Path('b')]), \
             patch.object(d, 'running_paths', return_value=[]), patch('builtins.input', return_value='2'):
            self.assertEqual(d.choose_config(), Path('b'))

    def test_no_config_does_not_request_manual_path(self):
        with patch.object(d, 'discover_configs', return_value=[]), \
             patch.object(d, 'running_paths', return_value=[]), \
             patch('builtins.input', side_effect=AssertionError('no path prompts')):
            self.assertIsNone(d.choose_config())

    def test_schema_only_and_parameterized(self):
        class Connection:
            closed = False
            def cursor(self): return self
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, sql, params):
                self.sql, self.params = sql, params
            def fetchall(self):
                return [('bonuri', 'id', 'int', 'PRI'), ('istoric_z', 'nr_z', 'int', ''),
                        ('registru_casa', 'sold', 'decimal', '')]
            def close(self): self.closed = True
        conn = Connection()
        config = dict(unitypos_host='localhost', unitypos_database="synthetic'; DROP TABLE x;--",
                      unitypos_user='test', unitypos_password='SECRET', agent_token='TOKEN')
        result = d.database_report(config, lambda **kwargs: conn)
        self.assertEqual(conn.sql, d.SCHEMA_SQL)
        self.assertTrue(conn.sql.startswith('SELECT '))
        self.assertEqual(conn.params, (config['unitypos_database'],))
        self.assertTrue(conn.closed)
        self.assertEqual(result['business_rows_read'], 0)
        self.assertTrue(result['tables'][1]['candidate_z'])
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('TOKEN', json.dumps(result))

    def test_error_redaction(self):
        def fail(**kwargs): raise RuntimeError('password=SECRET token=TOKEN')
        result = d.database_report(dict(unitypos_database='x', unitypos_host='localhost', unitypos_user='test'), fail)
        self.assertEqual(result['status'], 'error')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(d.safe_error(Exception(1045, 'SECRET'))['mysql_code'], 1045)

    def test_file_scan_does_not_read_contents_or_follow_links(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / 'raport-z.pdf').write_text('PRIVATE-CONTENT')
            (root / 'config-fiscal.json').write_text('SECRET')
            (root / 'horeca-snackyou.state.db').write_text('STATE')
            (Path(outside) / 'hidden-z.pdf').write_text('OUTSIDE')
            (root / 'link').symlink_to(outside, target_is_directory=True)
            with patch.object(Path, 'read_text', side_effect=AssertionError('read contents')):
                result = d.file_report(root)
            self.assertEqual([f['path_relative_to_pos'] for f in result['files']], ['raport-z.pdf'])
            self.assertNotIn('PRIVATE-CONTENT', json.dumps(result))
            self.assertEqual((root / 'horeca-snackyou.state.db').read_text(), 'STATE')

    def test_root_rejected_and_result_bounded(self):
        self.assertEqual(d.file_report(Path('/'))['status'], 'invalid_folder')
        with tempfile.TemporaryDirectory() as directory:
            for n in range(205): (Path(directory) / f'raport-{n}.pdf').touch()
            result = d.file_report(directory)
            self.assertEqual(len(result['files']), 200)
            self.assertTrue(result['truncated'])

    def test_report_written_without_config_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'agent.json'
            config.write_text(json.dumps({'unitypos_password': 'SECRET', 'agent_token': 'TOKEN'}))
            with patch.object(d, '__file__', str(root / 'diagnostic.py')), \
                 patch.object(d, 'choose_config', return_value=config), \
                 patch.object(d, 'database_report', return_value={'status': 'ok'}), \
                 patch('builtins.input', return_value=''), patch('builtins.print'):
                d.main()
            report = next(root.glob('diagnostic-z-*.json')).read_text()
            self.assertNotIn('SECRET', report)
            self.assertNotIn('TOKEN', report)
            self.assertFalse(json.loads(report)['fiscal_source_verified'])


if __name__ == '__main__': unittest.main()
