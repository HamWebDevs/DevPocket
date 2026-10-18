"""Integration tests use temporary projects, never a user's checkout."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from devpocket.cli import main
from devpocket.common import files, redact, run, write_text
from devpocket.envtwin import compare
from devpocket.oopsfile import context, fence
from devpocket.reporadar import scan
from devpocket.undorun import checked_path

class ToolkitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = main(argv)
        return code, out.getvalue()

    def test_redaction(self):
        clean = redact('API_KEY="abcdef" password=hello --token hunter2 https://user:password@example.com Authorization: Bearer xyz.abc ghp_12345678901234567890')
        for secret in ('abcdef', 'hello', 'hunter2', 'user:password', 'xyz.abc', 'ghp_12345678901234567890'):
            self.assertNotIn(secret, clean)

    def test_private_key_redaction(self):
        self.assertNotIn('private-content', redact('-----BEGIN RSA PRIVATE KEY-----\nprivate-content\n-----END RSA PRIVATE KEY-----'))

    def test_process_output_and_exit(self):
        r = run([sys.executable, '-c', "import sys;print('out');print('err',file=sys.stderr);sys.exit(7)"])
        self.assertEqual(r['returncode'], 7)
        self.assertIn('out', r['stdout'])
        self.assertIn('err', r['stderr'])

    def test_timeout(self):
        r = run([sys.executable, '-c', 'import time;time.sleep(10)'], timeout=.1)
        self.assertEqual(r['returncode'], 124)
        self.assertTrue(r['timed_out'])
        self.assertLess(r['seconds'], 4)

    def test_bounded_output(self):
        r = run([sys.executable, '-c', "print('x'*300000)"])
        self.assertLessEqual(len(r['stdout']), 128 * 1024)
        self.assertTrue(r['truncated'][0])

    def test_reports_never_overwrite(self):
        p = self.root / 'report'
        write_text(p, 'first')
        with self.assertRaises(FileExistsError):
            write_text(p, 'second')
        self.assertEqual(p.read_text(), 'first')

    def test_excluded_files(self):
        for n in ('.env', 'secret.key', 'good.py', '.env.example'):
            (self.root / n).write_text('x')
        self.assertEqual({p.name for p in files(self.root)}, {'good.py', '.env.example'})

    def test_failure_report(self):
        p = self.root / 'report.md'
        (self.root / 'crash.py').write_text("raise RuntimeError('token=hiddenvalue')\n")
        code, out = self.cli(['oopsfile', 'run', '--root', str(self.root), '--output', str(p), '--include-source', '--', sys.executable, 'crash.py'])
        self.assertEqual(code, 1, out)
        text = p.read_text()
        self.assertIn('RuntimeError', text)
        self.assertIn('crash.py:1', text)
        self.assertNotIn('hiddenvalue', text)

    def test_success_creates_no_report(self):
        p = self.root / 'report.md'
        code, _ = self.cli(['oopsfile', 'run', '--output', str(p), '--', sys.executable, '-c', "print('ok')"])
        self.assertEqual(code, 0)
        self.assertFalse(p.exists())

    def test_source_is_opt_in(self):
        p = self.root / 'report.md'
        (self.root / 'crash.py').write_text("# PRIVATE_SOURCE_MARKER\nraise ValueError('bad')\n")
        self.cli(['oopsfile', 'run', '--root', str(self.root), '--output', str(p), '--', sys.executable, 'crash.py'])
        self.assertNotIn('PRIVATE_SOURCE_MARKER', p.read_text())

    def test_source_stays_in_root(self):
        self.assertEqual(context('File "/etc/passwd", line 1', self.root), '')

    def test_embedded_markdown_fences(self):
        self.assertTrue(fence('```\nx\n```').startswith('````\n'))

    def test_environment_diff(self):
        a = {'schema': 1, 'packages': {'sample': '1'}}
        b = {'schema': 1, 'packages': {'sample': '2', 'new': '1'}}
        self.assertEqual(len(compare(a, b)), 2)
        self.assertEqual(compare(a, a), [])

    def test_environment_schema(self):
        with self.assertRaises(ValueError):
            compare({}, {})

    def test_snapshot_omits_environment_values(self):
        p = self.root / 'env.json'
        with mock.patch.dict(os.environ, {'VERY_SECRET_TOKEN': 'never-export-me'}):
            code, _ = self.cli(['envtwin', 'snapshot', '--output', str(p)])
        self.assertEqual(code, 0)
        self.assertNotIn('never-export-me', p.read_text())
        self.assertNotIn('VERY_SECRET_TOKEN', p.read_text())

    def make_run(self):
        (self.root / 'edited.txt').write_text('before')
        (self.root / 'deleted.txt').write_text('keep')
        script = "from pathlib import Path;Path('edited.txt').write_text('after');Path('deleted.txt').unlink();Path('new.txt').write_text('created')"
        code, out = self.cli(['undorun', 'run', '--root', str(self.root), '--', sys.executable, '-c', script])
        self.assertEqual(code, 0, out)
        return next((self.root / '.devpocket/runs').iterdir()).name

    def test_undo_preview_and_apply(self):
        rid = self.make_run()
        argv = ['undorun', 'restore', rid, '--root', str(self.root)]
        code, out = self.cli(argv)
        self.assertEqual(code, 0, out)
        self.assertEqual((self.root / 'edited.txt').read_text(), 'after')
        code, out = self.cli([*argv, '--apply'])
        self.assertEqual(code, 0, out)
        self.assertEqual((self.root / 'edited.txt').read_text(), 'before')
        self.assertEqual((self.root / 'deleted.txt').read_text(), 'keep')
        self.assertFalse((self.root / 'new.txt').exists())

    def test_conflict_aborts_before_any_restore(self):
        rid = self.make_run()
        (self.root / 'edited.txt').write_text('later work')
        code, out = self.cli(['undorun', 'restore', rid, '--root', str(self.root), '--apply'])
        self.assertEqual(code, 2)
        self.assertIn('conflict', out.lower())
        self.assertFalse((self.root / 'deleted.txt').exists())
        self.assertTrue((self.root / 'new.txt').exists())

    def test_backup_limit_prevents_command(self):
        (self.root / 'large.bin').write_bytes(b'x' * (8 * 1024 * 1024 + 1))
        code, _ = self.cli(['undorun', 'run', '--root', str(self.root), '--', sys.executable, '-c', "open('should-not-exist','w').close()"])
        self.assertEqual(code, 2)
        self.assertFalse((self.root / 'should-not-exist').exists())

    def test_damaged_backup_prevents_restore(self):
        rid = self.make_run()
        for p in (self.root / '.devpocket/runs' / rid / 'backup').iterdir():
            p.write_text('corrupt')
        code, _ = self.cli(['undorun', 'restore', rid, '--root', str(self.root), '--apply'])
        self.assertEqual(code, 2)
        self.assertEqual((self.root / 'edited.txt').read_text(), 'after')

    def test_traversal_is_refused(self):
        for n in ('../outside', '/etc/passwd', '.devpocket/secret', 'a\\b', 'C:/test'):
            with self.assertRaises(ValueError, msg=n):
                checked_path(self.root, n)

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink fixture')
    def test_symlink_restore_is_refused(self):
        rid = self.make_run()
        (self.root / 'edited.txt').unlink()
        (self.root / 'edited.txt').symlink_to(self.root / 'new.txt')
        code, out = self.cli(['undorun', 'restore', rid, '--root', str(self.root), '--apply'])
        self.assertEqual(code, 2)
        self.assertIn('Symlink', out)

    def test_flake_mixed_outcomes(self):
        p = self.root / 'flake.json'
        script = "from pathlib import Path;import sys;p=Path('counter');n=int(p.read_text())+1 if p.exists() else 1;p.write_text(str(n));print('token=hiddenvalue');sys.exit(n%2)"
        code, out = self.cli(['flaketrail', '--runs', '4', '--root', str(self.root), '--output', str(p), '--', sys.executable, '-c', script])
        self.assertEqual(code, 1, out)
        data = json.loads(p.read_text())
        self.assertEqual(data['summary']['passes'], 2)
        self.assertEqual(data['summary']['failures'], 2)
        self.assertTrue(data['summary']['mixed_outcomes'])
        self.assertNotIn('hiddenvalue', p.read_text())

    def test_radar_evidence_and_env_example(self):
        (self.root / 'README.md').write_text('[broken](missing.md)\n[remote](https://example.com)\n```md\n[example](imaginary.md)\n```\n')
        (self.root / 'app.py').write_text("import os\nkey = os.environ['REQUIRED_KEY']\n")
        (self.root / 'package.json').write_text(json.dumps({'scripts': {'start': 'node missing.js'}}))
        found = scan(self.root)
        self.assertTrue({'broken-local-link', 'missing-script', 'undocumented-env'} <= {f['code'] for f in found})
        self.assertEqual(len([f for f in found if f['code'] == 'broken-local-link']), 1)
        (self.root / '.env.example').write_text('REQUIRED_KEY=\n')
        self.assertNotIn('undocumented-env', {f['code'] for f in scan(self.root)})

    def test_radar_ignores_environment_access_inside_strings(self):
        (self.root / 'example.py').write_text('example = "os.environ[\'NOT_A_REAL_REQUIREMENT\']"\n')
        self.assertNotIn('undocumented-env', {f['code'] for f in scan(self.root)})

    def test_nonfinite_timeouts_rejected(self):
        for timeout in (float('nan'), float('inf'), -1):
            with self.assertRaises(ValueError):
                run([sys.executable, '-c', 'pass'], timeout=timeout)

    def test_radar_never_executes_scripts(self):
        (self.root / 'package.json').write_text('{"scripts":{"test":"touch dangerous"}}')
        scan(self.root)
        self.assertFalse((self.root / 'dangerous').exists())

    def test_missing_executable_is_handled(self):
        code, _ = self.cli(['oopsfile', 'run', '--', 'devpocket-no-such-executable-12345'])
        self.assertEqual(code, 2)

if __name__ == '__main__':
    unittest.main()
