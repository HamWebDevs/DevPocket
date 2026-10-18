"""Regression tests for streaming log analysis and static import diagnostics."""
import contextlib
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from devpocket.cli import main
from devpocket.importdoctor import inspect_module, locate
from devpocket.loglens import analyse, bounded_lines, parse_line, safe_text


class LogLensTests(unittest.TestCase):
    def analyse(self, text, **kwargs):
        return analyse([('fixture.log', io.StringIO(text))], **kwargs)

    def test_normalised_group_counts_and_locations(self):
        data = self.analyse('2026-10-18T10:00:00Z ERROR request 123 failed\n2026-10-18T10:01:00Z ERROR request 456 failed\n2026-10-18T10:02:00Z INFO healthy\n')
        self.assertEqual(data['records_scanned'], 3)
        self.assertEqual(data['records_matched'], 2)
        group = data['groups'][0]
        self.assertEqual(group['count'], 2)
        self.assertEqual(group['first_seen']['line'], 1)
        self.assertEqual(group['last_seen']['timestamp'], '2026-10-18T10:01:00Z')

    def test_exact_keeps_numbers_distinct(self):
        self.assertEqual(len(self.analyse('ERROR status 404\nERROR status 500\n', exact=True)['groups']), 2)

    def test_json_lines_levels_and_messages(self):
        data = self.analyse('{"level":"error","timestamp":"10:00","message":"job 123 failed"}\n{"levelname":"ERROR","time":"10:01","msg":"job 456 failed"}\n')
        self.assertEqual(data['groups'][0]['count'], 2)
        self.assertEqual(data['groups'][0]['last_seen']['timestamp'], '10:01')

    def test_python_traceback_is_one_record(self):
        data = self.analyse('Traceback (most recent call last):\n  File "app.py", line 1, in <module>\n    bad()\nValueError: bad value\n')
        self.assertEqual(data['records_scanned'], 1)
        self.assertEqual(data['groups'][0]['level'], 'ERROR')
        self.assertIn('ValueError', data['groups'][0]['samples'][0])

    def test_plain_record_after_traceback_is_not_swallowed(self):
        data = self.analyse('Traceback (most recent call last):\n  File "app.py", line 1\nValueError: broken\nplain next record\n', include_all=True)
        self.assertEqual(data['records_scanned'], 2)

    def test_truncated_gzip_is_a_handled_input_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'broken.gz'
            path.write_bytes(gzip.compress(b'ERROR failed\n')[:-8])
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['loglens', str(path)]), 2)

    def test_continuations_and_multiline_groups(self):
        data = self.analyse('ERROR operation failed\n    at worker line 1\nINFO continuing\n')
        self.assertEqual(data['records_scanned'], 2)
        self.assertIn('worker', data['groups'][0]['samples'][0])

    def test_plain_lines_need_all_flag(self):
        self.assertEqual(self.analyse('arbitrary plain line\n')['records_matched'], 0)
        self.assertEqual(self.analyse('arbitrary plain line\n', include_all=True)['records_matched'], 1)

    def test_level_words_inside_plain_messages_are_not_headers(self):
        self.assertEqual(parse_line('some description mentioning ERROR')[0], 'UNKNOWN')

    def test_redaction_and_terminal_escape_removal(self):
        text = safe_text('\x1b[31mERROR token=supersecret\x1b[0m\x00')
        self.assertNotIn('supersecret', text)
        self.assertNotIn('\x1b', text)
        self.assertNotIn('\x00', text)

    def test_group_limit_is_explicit(self):
        data = self.analyse('ERROR apple\nERROR banana\nERROR apple\n', max_groups=1)
        self.assertEqual(data['ungrouped_records'], 1)
        self.assertEqual(data['groups'][0]['count'], 2)

    def test_oversized_lines_keep_physical_line_numbers(self):
        rows = list(bounded_lines(io.StringIO('x' * 150000 + '\nERROR second line\n')))
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0][2])
        self.assertLess(len(rows[0][1]), 66000)
        self.assertEqual(rows[1][0], 2)

    def test_multiple_inputs_keep_source_evidence(self):
        data = analyse([('one.log', io.StringIO('ERROR failed 1\n')), ('two.log', io.StringIO('ERROR failed 2\n'))])
        self.assertEqual(data['groups'][0]['count'], 2)
        self.assertEqual(data['groups'][0]['last_seen']['source'], 'two.log')

    def test_malformed_json_stays_plain_text(self):
        self.assertEqual(parse_line('{broken')[0], 'UNKNOWN')

    def test_gzip_and_stdin_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'events.log.gz'
            with gzip.open(p, 'wt', encoding='utf-8') as f:
                f.write('ERROR gzip failure\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out), mock.patch('sys.stdin', io.StringIO('ERROR stdin failure\n')):
                code = main(['loglens', str(p), '-', '--json'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())['records_matched'], 2)


class ImportDoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.mapping = mock.patch('devpocket.importdoctor.metadata.packages_distributions', return_value={})
        self.mapping.start()

    def tearDown(self):
        self.mapping.stop()
        self.tmp.cleanup()

    def test_stdlib_resolution(self):
        data = inspect_module('json', self.root)
        self.assertTrue(data['resolution']['found'])
        self.assertFalse(data['has_problems'])

    def test_local_stdlib_shadow(self):
        (self.root / 'json.py').write_text("raise RuntimeError('must not execute')\n")
        data = inspect_module('json', self.root)
        self.assertTrue(data['has_problems'])
        self.assertIn('local-shadow', {f['code'] for f in data['findings']})
        self.assertEqual(Path(data['resolution']['origin']), self.root / 'json.py')

    def test_dotted_packages_do_not_execute_init(self):
        package = self.root / 'example_package'
        package.mkdir()
        (package / '__init__.py').write_text("raise RuntimeError('must not execute')\n")
        (package / 'child.py').write_text("raise RuntimeError('must not execute')\n")
        data = inspect_module('example_package.child', self.root)
        self.assertTrue(data['resolution']['found'])
        self.assertEqual(Path(data['resolution']['origin']), package / 'child.py')

    def test_missing_child_of_regular_module(self):
        (self.root / 'single.py').write_text('value = 1\n')
        data = inspect_module('single.child', self.root)
        self.assertFalse(data['resolution']['found'])
        self.assertIn('not a package', data['resolution']['missing_at'])

    def test_namespace_package(self):
        (self.root / 'devpocket_test_namespace').mkdir()
        data = inspect_module('devpocket_test_namespace', self.root)
        self.assertTrue(data['resolution']['found'])
        self.assertIn('namespace-package', {f['code'] for f in data['findings']})

    def test_nested_namespace_packages_without_importing_parents(self):
        package = self.root / 'devpocket_nested_ns' / 'child'
        package.mkdir(parents=True)
        (package / 'leaf.py').write_text("raise RuntimeError('must not execute')\n")
        data = inspect_module('devpocket_nested_ns.child.leaf', self.root)
        self.assertTrue(data['resolution']['found'])
        self.assertEqual(Path(data['resolution']['origin']), package / 'leaf.py')

    def test_missing_import(self):
        data = inspect_module('devpocket_nonexistent_module_987654321', self.root)
        self.assertTrue(data['has_problems'])
        self.assertIn('module-not-found', {f['code'] for f in data['findings']})

    def test_expected_interpreter_comparison(self):
        data = inspect_module('json', self.root, expected_python=str(self.root / 'another-python'))
        self.assertIn('interpreter-mismatch', {f['code'] for f in data['findings']})
        same = inspect_module('json', self.root, expected_python=sys.executable)
        self.assertNotIn('interpreter-mismatch', {f['code'] for f in same['findings']})

    def test_missing_distribution(self):
        data = inspect_module('json', self.root, distribution='devpocket-never-installed-dist-654321')
        self.assertIn('distribution-not-installed', {f['code'] for f in data['findings']})

    def test_builtins_take_precedence_over_local_files(self):
        (self.root / 'sys.py').write_text("raise RuntimeError('must not execute')\n")
        spec, missing = locate('sys', [str(self.root)])
        self.assertEqual(spec.origin, 'built-in')
        self.assertIsNone(missing)

    def test_invalid_import_names(self):
        for name in ('../oops', 'foo..bar', 'some-name', 'a;print(1)'):
            with self.assertRaises(ValueError):
                inspect_module(name, self.root)

    def test_json_cli_exit_status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['importdoctor', 'devpocket_nonexistent_module_987654321', '--root', str(self.root), '--json'])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.getvalue())['resolution']['found'])

if __name__ == '__main__':
    unittest.main()
