"""Cache invalidation, isolation, failure semantics and real-worker regression tests."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from devpocket import cache
from devpocket.checks import pipeline
from devpocket.cli import main
from devpocket.engine import execute, gated_exit
from devpocket.project import validate
from devpocket.reports import create_baseline
from devpocket.sdk import Finding, ToolResult, ToolSpec


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / 'input.txt').write_text('original', encoding='utf-8')
        self.calls = 0
        self.policy = {'inputs': ['input.txt'], 'env': ['DEVPOCKET_CACHE_TEST']}

    def run_tool(self, *, contract='v1', allow_exec=False, policy=None, mutate=False, fail=False):
        def diagnostic(context, params):
            self.calls += 1
            text = (context.root / 'input.txt').read_text(encoding='utf-8')
            if mutate:
                (context.root / 'input.txt').write_text(text + ' changed', encoding='utf-8')
            if fail:
                raise ValueError('diagnostic failed')
            return ToolResult('inspected', [Finding('test', 'stable warning')], {'content': text})
        spec = ToolSpec('example', 'Example cached diagnostic', {'type': 'object'}, diagnostic, cache_version=contract)
        return execute('example', {}, self.root, allow_exec=allow_exec, registry=SimpleNamespace(get=lambda name: spec), cache_policy=self.policy if policy is None else policy)

    def test_second_run_reuses_raw_findings_and_preserves_gate(self):
        first, second = self.run_tool(), self.run_tool()
        self.assertEqual([first['cache']['status'], second['cache']['status']], ['miss', 'hit'])
        self.assertEqual(self.calls, 1)
        self.assertEqual(first['findings'], second['findings'])
        self.assertEqual(gated_exit(second), 1)

    def test_same_size_content_change_invalidates_even_with_restored_mtime(self):
        self.run_tool()
        path = self.root / 'input.txt'
        before = path.stat()
        path.write_text('modified', encoding='utf-8')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        result = self.run_tool()
        self.assertEqual(result['cache']['status'], 'miss')
        self.assertEqual(result['data']['content'], 'modified')
        self.assertEqual(self.calls, 2)

    def test_directory_additions_deletions_and_missing_paths_invalidate(self):
        policy = {'inputs': ['folder', 'missing.txt']}
        (self.root / 'folder').mkdir()
        self.run_tool(policy=policy)
        self.assertEqual(self.run_tool(policy=policy)['cache']['status'], 'hit')
        (self.root / 'folder' / 'new.txt').write_text('new')
        self.assertEqual(self.run_tool(policy=policy)['cache']['status'], 'miss')
        (self.root / 'folder' / 'new.txt').unlink()
        (self.root / 'missing.txt').write_text('created')
        self.assertEqual(self.run_tool(policy=policy)['cache']['status'], 'miss')

    def test_declared_environment_changes_are_hashed_not_stored(self):
        with mock.patch.dict(os.environ, {'DEVPOCKET_CACHE_TEST': 'private-example-value-one'}):
            self.run_tool()
            self.assertEqual(self.run_tool()['cache']['status'], 'hit')
        with mock.patch.dict(os.environ, {'DEVPOCKET_CACHE_TEST': 'private-example-value-two'}):
            self.assertEqual(self.run_tool()['cache']['status'], 'miss')
        for path in cache.directory(self.root).glob('*.json'):
            self.assertNotIn('private-example-value', path.read_text())

    def test_contract_and_runtime_changes_invalidate(self):
        with mock.patch('devpocket.cache.runtime_identity', return_value='old-runtime'):
            self.run_tool()
            self.assertEqual(self.run_tool(contract='v2')['cache']['status'], 'miss')
        with mock.patch('devpocket.cache.runtime_identity', return_value='new-runtime'):
            self.assertEqual(self.run_tool()['cache']['status'], 'miss')

    def test_non_opted_in_tools_and_execution_permissions_bypass(self):
        for kwargs in ({'contract': None}, {'allow_exec': True}, {'policy': False}):
            self.assertEqual(self.run_tool(**kwargs)['cache']['status'], 'bypass')
        self.assertEqual(self.calls, 3)
        self.assertFalse(cache.directory(self.root).exists())

    def test_failures_and_mutating_inputs_are_not_saved(self):
        self.assertEqual(self.run_tool(fail=True)['status'], 'error')
        self.assertEqual(self.run_tool(fail=True)['status'], 'error')
        self.assertEqual(self.run_tool(mutate=True)['cache']['status'], 'bypass')
        self.assertEqual(cache.manage(self.root)['entries'], 0)

    def test_corruption_and_expiry_trigger_real_execution(self):
        self.run_tool()
        path = next(cache.directory(self.root).glob('*.json'))
        data = json.loads(path.read_text())
        data['report']['data']['content'] = 'corrupted'
        path.write_text(json.dumps(data))
        self.assertEqual(self.run_tool()['cache']['status'], 'miss')
        data = json.loads(path.read_text())
        data['created'] -= 7200
        path.write_text(json.dumps(data))
        self.assertEqual(self.run_tool()['cache']['status'], 'miss')
        self.assertEqual(self.calls, 3)

    def test_resource_limit_bypasses_without_hiding_diagnostic(self):
        with mock.patch('devpocket.cache.MAX_BYTES', 4):
            report = self.run_tool()
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['cache']['status'], 'bypass')
        self.assertEqual(self.calls, 1)

    def test_structurally_invalid_cached_report_cannot_replace_execution(self):
        self.run_tool()
        path = next(cache.directory(self.root).glob('*.json'))
        data = json.loads(path.read_text())
        data['report'] = None
        data['integrity'] = cache.digest(None)
        path.write_text(json.dumps(data))
        self.assertEqual(self.run_tool()['cache']['status'], 'miss')
        self.assertEqual(self.calls, 2)

    def test_failed_hit_recheck_runs_diagnostic_instead_of_returning_stale_data(self):
        self.run_tool()
        original = cache.snapshot
        calls = 0
        def unreliable(root, policy):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('input became unreadable')
            return original(root, policy)
        with mock.patch('devpocket.cache.snapshot', side_effect=unreliable):
            result = self.run_tool()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['cache']['status'], 'bypass')
        self.assertEqual(self.calls, 2)

    def test_storage_is_bounded_and_clear_preserves_unrelated_files(self):
        with mock.patch('devpocket.cache.MAX_ENTRIES', 2):
            for contract in ('v1', 'v2', 'v3'):
                self.run_tool(contract=contract)
        path = cache.directory(self.root) / 'user-notes.txt'
        path.write_text('keep')
        self.assertEqual(cache.manage(self.root)['entries'], 2)
        self.assertEqual(cache.manage(self.root, clear=True)['removed'], 2)
        self.assertEqual(path.read_text(), 'keep')

    def test_symlink_inputs_and_cache_directories_are_refused(self):
        try:
            (self.root / 'linked').symlink_to(self.root / 'input.txt')
        except OSError:
            self.skipTest('Symlink creation unavailable')
        self.assertEqual(self.run_tool(policy={'inputs': ['linked']})['cache']['status'], 'bypass')
        external = self.root / 'outside'
        external.mkdir()
        existing = self.root / '.devpocket' / 'cache-v1'
        existing.rmdir()
        existing.symlink_to(external, target_is_directory=True)
        self.assertEqual(self.run_tool()['cache']['status'], 'bypass')
        with self.assertRaises(ValueError):
            cache.manage(self.root, clear=True)
        self.assertEqual(list(external.iterdir()), [])

    def test_cache_configuration_boundaries(self):
        for policy in ({}, {'inputs': ['../outside']}, {'inputs': ['/absolute']}, {'inputs': ['C:/file']}, {'inputs': ['*.py']}, {'inputs': ['x/.git']}, {'inputs': ['input.txt'], 'env': ['invalid-name']}, {'inputs': ['input.txt'], 'max_age': float('nan')}):
            with self.assertRaises(ValueError):
                validate({'version': 1, 'checks': {'test': {'tool': 'loglens', 'cache': policy}}})
        with self.assertRaises(ValueError):
            ToolSpec('bad', 'invalid', {'type': 'object'}, lambda c, p: None, read_only=False, cache_version='v1')

    def test_real_worker_cache_reapplies_baseline_and_dependency_gates(self):
        (self.root / 'events.log').write_text('ERROR operation failed\n')
        config = {'version': 1, 'checks': {'logs': {'tool': 'loglens', 'input': {'paths': ['events.log']}, 'cache': {'inputs': ['events.log']}}, 'next': {'tool': 'envtwin', 'needs': ['logs']}}}
        first = pipeline(config, self.root)
        self.assertEqual(first['checks'][0]['report']['cache']['status'], 'miss')
        second = pipeline(config, self.root)
        self.assertEqual(second['checks'][0]['report']['cache']['status'], 'hit')
        self.assertEqual(second['checks'][1]['status'], 'skipped')
        source, baseline = self.root / 'report.json', self.root / 'baseline.json'
        source.write_text(json.dumps(first))
        create_baseline(source, baseline)
        existing = pipeline(config, self.root, baseline=baseline)
        self.assertEqual(existing['exit_code'], 0)
        self.assertEqual(existing['checks'][0]['report']['cache']['status'], 'hit')
        (self.root / 'events.log').unlink()
        failed = pipeline(config, self.root, baseline=baseline)
        self.assertEqual(failed['exit_code'], 2)
        self.assertEqual(failed['checks'][1]['status'], 'skipped')

    def test_cli_no_cache_and_cache_management(self):
        (self.root / 'events.log').write_text('INFO completed\n')
        config = {'version': 1, 'checks': {'logs': {'tool': 'loglens', 'input': {'paths': ['events.log']}, 'cache': {'inputs': ['events.log']}}}}
        (self.root / '.devpocket.json').write_text(json.dumps(config))
        def cli(args):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([*args, '--root', str(self.root)])
            return code, json.loads(output.getvalue())
        cli(['check', '--format', 'json'])
        _, fresh = cli(['check', '--format', 'json', '--no-cache'])
        self.assertEqual(fresh['checks'][0]['report']['cache']['status'], 'bypass')
        self.assertEqual(cli(['cache', 'status', '--json'])[1]['entries'], 1)
        self.assertEqual(cli(['cache', 'clear', '--json'])[1]['removed'], 1)


if __name__ == '__main__':
    unittest.main()
