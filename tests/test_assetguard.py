"""Production-artifact evidence, stable comparisons and deploy/CI boundaries."""
import contextlib
import copy
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from devpocket import assetguard
from devpocket.cli import main
from devpocket.engine import execute, gated_exit


class AssetGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.build = self.root / 'dist'
        self.build.mkdir()

    def write(self, name, value=b'console.log("hello");\n'):
        path = self.build / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode() if isinstance(value, str) else value)
        return path

    def cli(self, args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(['assetguard', '--root', str(self.build), *args])
        return code, output.getvalue(), errors.getvalue()

    def test_inventory_measures_actual_bytes_and_deterministic_gzip(self):
        script = self.write('assets/app.12345678.js')
        self.write('index.html', '<script src="/assets/app.12345678.js?v=3#x"></script>')
        report = assetguard.analyse(self.build)
        self.assertEqual(report, assetguard.analyse(self.build))
        self.assertFalse(report['findings'])
        self.assertEqual(report['summary']['local_resource_references'], 1)
        row = next(r for r in report['snapshot']['files'] if r['path'].endswith('.js'))
        self.assertEqual(row['gzip_bytes'], len(gzip.compress(script.read_bytes(), compresslevel=9, mtime=0)))
        self.assertEqual(report['summary']['by_kind']['script']['files'], 1)

    def test_deployment_mount_base_element_and_nested_pages(self):
        self.write('assets/app.js')
        self.write('docs/index.html', '<script src="../assets/app.js?x=1&amp;y=2"></script><base href="/project/"><link rel="modulepreload" href="assets/app.js"><img src="https://cdn.example.invalid/logo.png">')
        self.write('index.html', '<script src="/project/assets/app.js"></script>')
        # The first base applies to every reference, including those before it.
        report = assetguard.analyse(self.build, public_path='/project/')
        self.assertEqual([f['rule'] for f in report['findings']], ['resource-outside-public-path'])
        self.assertEqual(report['summary']['external_resource_references'], 1)
        self.write('docs/index.html', '<base href="/project/"><script src="assets/app.js"></script>')
        self.assertFalse(assetguard.analyse(self.build, public_path='/project/')['findings'])

    def test_missing_resources_are_located_and_external_code_is_not_opened(self):
        self.write('index.html', '<link rel="stylesheet" href="gone.css">\n<script src="https://example.invalid/a.js"></script>\n<img src="data:image/png;base64,AA">')
        report = assetguard.analyse(self.build)
        issue = report['findings'][0]
        self.assertEqual((issue['rule'], issue['path'], issue['line'], issue['severity']), ('missing-build-resource', 'index.html', 1, 'error'))
        self.assertEqual(report['summary']['external_resource_references'], 2)

    def test_encoded_traversal_cannot_resolve_outside_deployment(self):
        self.write('index.html', '<script src="/project/%2e%2e/private.js"></script><img src="/project/%5csecret.png">')
        rules = {f['rule'] for f in assetguard.analyse(self.build, public_path='/project/')['findings']}
        self.assertEqual(rules, {'resource-outside-public-path', 'invalid-resource-url'})

    def test_private_assets_are_flagged_without_reading_contents(self):
        private = self.write('.env.production', 'NEVER-READ-THIS')
        self.write('app.js.map', '{"sourcesContent":["intentional public source"]}')
        original = Path.open

        def guarded(path, *args, **kwargs):
            self.assertNotEqual(path, private)
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, 'open', guarded):
            report = assetguard.analyse(self.build, max_total_gzip_kib=100)
        self.assertNotIn('NEVER-READ-THIS', json.dumps(report))
        self.assertEqual({r['rule'] for r in report['findings']}, {'private-build-entry', 'published-source-map', 'asset-budget-unknown'})
        row = next(r for r in report['snapshot']['files'] if r['path'].startswith('.env'))
        self.assertIsNone(row['sha256'])

    def test_duplicate_payloads_and_identical_renames_use_content_hashes(self):
        self.write('app.aaaa1111.js')
        baseline = assetguard.analyse(self.build)['snapshot']
        (self.build / 'app.aaaa1111.js').rename(self.build / 'app.bbbb2222.js')
        report = assetguard.analyse(self.build, baseline=baseline, max_growth_kib=0)
        delta = report['comparison']
        self.assertEqual(delta['gzip_delta_bytes'], 0)
        self.assertEqual(delta['new_unique_content_gzip_bytes'], 0)
        self.assertEqual(delta['renamed_identical'], [{'before': 'app.aaaa1111.js', 'after': 'app.bbbb2222.js'}])
        self.write('copy.js')
        duplicates = assetguard.analyse(self.build)['duplicates']
        self.assertEqual(duplicates[0]['paths'], ['app.bbbb2222.js', 'copy.js'])
        self.assertGreater(duplicates[0]['redundant_raw_bytes'], 0)

    def test_growth_asset_and_total_budgets_are_independent(self):
        self.write('app.js', 'x')
        baseline = assetguard.analyse(self.build)['snapshot']
        self.write('app.js', bytes(range(256)) * 8)
        report = assetguard.analyse(self.build, baseline=baseline, max_growth_kib=0, max_asset_gzip_kib=0, max_total_gzip_kib=0)
        self.assertEqual({r['rule'] for r in report['findings']}, {'gzip-growth-budget', 'asset-gzip-budget', 'total-gzip-budget'})
        self.assertEqual(report['comparison']['changed'], ['app.js'])
        self.assertGreater(report['comparison']['new_unique_content_gzip_bytes'], 0)

    def test_unknown_baseline_measurements_cannot_pass_growth_gate(self):
        self.write('app.js')
        (self.build / '.git').mkdir()
        baseline = assetguard.analyse(self.build)['snapshot']
        (self.build / '.git').rmdir()
        report = assetguard.analyse(self.build, baseline=baseline, max_growth_kib=0)
        self.assertFalse(report['comparison']['comparable'])
        self.assertIsNone(report['comparison']['gzip_delta_bytes'])
        self.assertEqual(report['findings'][0]['rule'], 'asset-budget-unknown')

    def test_bad_budgets_and_baselines_are_rejected(self):
        self.write('app.js')
        baseline = assetguard.analyse(self.build)['snapshot']
        for value in [float('nan'), float('inf'), -1, True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                assetguard.analyse(self.build, max_total_gzip_kib=value)
        with self.assertRaises(ValueError):
            assetguard.analyse(self.build, max_growth_kib=1)
        for changes in [{'schema': True}, {'compression': 'brotli'}, {'files': baseline['files'] * 2}, {'files': [{**baseline['files'][0], 'path': '../escape'}]}, {'files': [{**baseline['files'][0], 'raw_bytes': True}]}]:
            invalid = copy.deepcopy(baseline)
            invalid.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                assetguard.analyse(self.build, baseline=invalid)
        with self.assertRaises(ValueError):
            assetguard.analyse(self.build, baseline=baseline, public_path='/other/')

    def test_limits_empty_build_and_unsafe_mount_fail_explicitly(self):
        with self.assertRaises(ValueError):
            assetguard.analyse(self.build)
        self.write('a.js')
        self.write('b.js', 'b')
        with mock.patch.object(assetguard, 'MAX_FILES', 1), self.assertRaises(ValueError):
            assetguard.analyse(self.build)
        for mount in ['https://example.invalid/', '//example.invalid/', '/foo/../', '/foo/?query=1', '/foo/%00/', '/foo/%23/', '/foo/%2520/']:
            with self.subTest(mount=mount), self.assertRaises(ValueError):
                assetguard.analyse(self.build, public_path=mount)

    def test_compressor_changes_do_not_masquerade_as_size_regressions(self):
        self.write('app.js')
        baseline = assetguard.analyse(self.build)['snapshot']
        baseline['compressor'] = '0.0-test'
        report = assetguard.analyse(self.build, baseline=baseline, max_growth_kib=0)
        self.assertFalse(report['comparison']['comparable'])
        self.assertEqual(report['findings'][0]['rule'], 'asset-budget-unknown')
        self.assertFalse(assetguard.analyse(self.build, baseline=baseline, max_total_gzip_kib=100)['findings'])

    def test_symlinks_are_refused(self):
        self.write('a.js')
        try:
            (self.build / 'link.js').symlink_to(self.build / 'a.js')
        except OSError:
            self.skipTest('Symlink creation unavailable')
        with self.assertRaises(ValueError):
            assetguard.analyse(self.build)

    def test_cli_snapshots_are_exclusive_and_outside_build(self):
        self.write('a.js')
        snapshot = self.root / 'snapshot.json'
        code, output, errors = self.cli(['--snapshot', str(snapshot), '--json'])
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)['tool'], 'assetguard')
        assetguard.validate_snapshot(json.loads(snapshot.read_text()))
        with mock.patch.object(assetguard, 'analyse') as run:
            self.assertEqual(self.cli(['--snapshot', str(snapshot)])[0], 2)
            run.assert_not_called()
        self.assertEqual(self.cli(['--snapshot', str(self.build / 'snapshot.json')])[0], 2)
        self.assertFalse((self.build / 'snapshot.json').exists())
        self.assertEqual(self.cli(['--baseline', str(snapshot), '--max-asset-gzip-kib', '0'])[0], 1)

    def test_structured_adapter_gates_and_uses_project_relative_locations(self):
        self.write('index.html', '<script src="missing.js"></script>')
        report = execute('assetguard', {'path': 'dist'}, self.root)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['findings'][0]['path'], 'dist/index.html')
        self.assertEqual(gated_exit(report), 1)
        self.assertEqual(execute('assetguard', {'path': '../'}, self.root)['status'], 'error')
        self.assertEqual(execute('assetguard', {'path': 'dist', 'max_growth_kib': 0}, self.root)['status'], 'error')

    def test_repeated_checks_rescan_new_deployment_metadata(self):
        self.write('app.js')
        policy = {'inputs': ['dist']}
        first = execute('assetguard', {'path': 'dist'}, self.root, cache_policy=policy)
        self.assertEqual(first['cache']['status'], 'bypass')
        (self.build / '.git').mkdir()
        second = execute('assetguard', {'path': 'dist'}, self.root, cache_policy=policy)
        self.assertEqual(second['cache']['status'], 'bypass')
        self.assertEqual(second['findings'][0]['rule'], 'private-build-entry')

    def test_observed_build_mutation_refuses_a_snapshot(self):
        path = self.write('app.js')
        original = gzip.compress

        def changing(payload, **options):
            path.write_bytes(b'x' * len(payload))
            return original(payload, **options)

        with mock.patch.object(gzip, 'compress', side_effect=changing), self.assertRaisesRegex(ValueError, 'changed during inspection'):
            assetguard.analyse(self.build)


if __name__ == '__main__':
    unittest.main()
