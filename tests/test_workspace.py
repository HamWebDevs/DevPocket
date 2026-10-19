"""Workspace scope, worker isolation, namespaces and bounded orchestration."""
import copy
import json
import os
from pathlib import Path
import threading
import unittest
from unittest import mock

from devpocket import __version__
from devpocket.engine import execute, failure
from devpocket.reports import create_baseline, sarif
from devpocket.sdk import Finding
from devpocket.workspace import check, compile_plan
from test_platform import TempTest


def result(tool='envtwin', finding=False):
    return {'schema': 1, 'version': __version__, 'tool': tool, 'status': 'completed', 'exit_code': 0, 'summary': 'ready', 'findings': [Finding('problem', 'Review this', path='file.py').as_dict()] if finding else [], 'data': {}}


class WorkspaceTests(TempTest):
    def setUp(self):
        super().setUp()
        self.manifest = {'version': 1, 'shared_inputs': ['shared'], 'projects': {'lib': {'path': 'packages/lib'}, 'web': {'path': 'apps/web', 'needs': ['lib']}, 'api': {'path': 'apps/api'}}}
        for definition in self.manifest['projects'].values():
            root = self.root / definition['path']
            root.mkdir(parents=True)
            (root / '.devpocket.json').write_text(json.dumps({'version': 1, 'checks': {'scan': {'tool': 'envtwin'}}}))
        self.save()

    def save(self):
        (self.root / '.devpocket-workspace.json').write_text(json.dumps(self.manifest))

    def selected(self, **kw):
        plan = compile_plan(self.root, **kw)[0]
        return {p['name'] for p in plan['projects'] if p['selected']}

    def test_cross_project_dag_includes_local_dependencies(self):
        path = self.root / 'apps/web/.devpocket.json'
        path.write_text(json.dumps({'version': 1, 'checks': {'scan': {'tool': 'envtwin'}, 'second': {'tool': 'envtwin', 'needs': ['scan']}}}))
        plan = compile_plan(self.root)[0]
        self.assertEqual(plan['levels'], [['lib/scan', 'api/scan'], ['web/scan'], ['web/second']])
        self.assertIn('lib/scan', plan['nodes'][2]['needs'])

    def test_changed_selection_expands_downstream_and_prerequisites(self):
        self.assertEqual(self.selected(changed=['packages/lib/deleted.py']), {'lib', 'web'})
        self.assertEqual(self.selected(changed=['apps/web/src/a.js']), {'lib', 'web'})
        self.assertEqual(self.selected(projects=['web']), {'lib', 'web'})
        self.assertEqual(self.selected(changed=['apps/api/a.py']), {'api'})
        self.assertEqual(self.selected(changed=[]), set())

    def test_watch_shared_config_and_unmapped_are_conservative(self):
        self.manifest['projects']['web']['watch'] = ['api-schema']
        self.save()
        self.assertEqual(self.selected(changed=['api-schema/types.json']), {'lib', 'web'})
        for path in ('shared/settings', 'README.md', '.devpocket-workspace.json', 'apps/api/.devpocket.json'):
            self.assertEqual(self.selected(changed=[path]), {'lib', 'web', 'api'})

    def test_plan_digest_changes_with_inputs_and_scope_without_exporting_inputs(self):
        plan = compile_plan(self.root)[0]
        path = self.root / 'apps/api/.devpocket.json'
        config = json.loads(path.read_text())
        config['checks']['scan']['input'] = {'secret': 'private-fixture-value'}
        path.write_text(json.dumps(config))
        new = compile_plan(self.root)[0]
        self.assertNotEqual(plan['plan_sha256'], new['plan_sha256'])
        self.assertNotIn('private-fixture-value', json.dumps(new))
        self.assertNotEqual(new['plan_sha256'], compile_plan(self.root, projects=['api'])[0]['plan_sha256'])

    def test_bad_manifest_paths_cycles_and_unknown_fields(self):
        for mutation in ('cycle', 'escape', 'duplicate', 'unknown'):
            original = copy.deepcopy(self.manifest)
            if mutation == 'cycle': self.manifest['projects']['lib']['needs'] = ['web']
            if mutation == 'escape': self.manifest['projects']['api']['path'] = '../escape'
            if mutation == 'duplicate': self.manifest['projects']['api']['path'] = 'apps/web'
            if mutation == 'unknown': self.manifest['script'] = 'ignored?'
            self.save()
            with self.assertRaises(ValueError): compile_plan(self.root)
            self.manifest = original
        self.save()
        for changed in (['../x'], ['/x'], ['a/./b'], [True], 'file'):
            with self.assertRaises(ValueError): compile_plan(self.root, changed=changed)
        with self.assertRaises(ValueError): compile_plan(self.root, projects=['web'], changed=[])

    @unittest.skipUnless(os.name == 'posix', 'symlink support')
    def test_parent_and_config_symlinks_refused(self):
        (self.root / 'alias').symlink_to(self.root / 'apps', target_is_directory=True)
        self.manifest['projects']['api']['path'] = 'alias/api'
        self.save()
        with self.assertRaises(ValueError): compile_plan(self.root)
        self.manifest['projects']['api']['path'] = 'apps/api'
        self.save()
        path = self.root / 'apps/api/.devpocket.json'
        path.unlink()
        path.symlink_to(self.root / 'apps/web/.devpocket.json')
        with self.assertRaises(ValueError): compile_plan(self.root)

    def test_expected_plan_baseline_and_output_preflight_before_workers(self):
        output = self.root / 'existing.json'
        output.write_text('unchanged')
        with mock.patch('devpocket.workspace.invoke') as worker:
            with self.assertRaises(ValueError): check(self.root, expect_plan='0' * 64)
            with self.assertRaises(ValueError): check(self.root, baseline=output)
            code, _, _ = self.cli(['workspace', 'check', '--root', str(self.root), '--output', str(output)])
            self.assertEqual(code, 2)
            worker.assert_not_called()

    def test_global_worker_limit_and_project_trust_scope(self):
        barrier = threading.Barrier(2, timeout=3)
        seen = []
        lock = threading.Lock()
        active = 0
        maximum = 0
        def worker(tool, params, root, plugins, allow_exec, timeout, cancel, cache):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                seen.append((root.relative_to(self.root).as_posix(), plugins, allow_exec, cache))
            if root.name in {'lib', 'api'}: barrier.wait()
            with lock: active -= 1
            return result(tool)
        with mock.patch('devpocket.workspace.invoke', side_effect=worker):
            report = check(self.root, jobs=2)
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(maximum, 2)
        self.assertEqual({x[0] for x in seen}, {'packages/lib', 'apps/web', 'apps/api'})
        self.assertTrue(all(x[1:] == ([], False, None) for x in seen))

    def test_failures_block_downstream_but_not_independent_project(self):
        def worker(tool, params, root, *args):
            return failure(tool, 'broken') if root.name == 'lib' else result(tool)
        with mock.patch('devpocket.workspace.invoke', side_effect=worker): report = check(self.root)
        self.assertEqual([r['status'] for r in report['checks']], ['failed', 'skipped', 'passed'])
        self.assertEqual(report['exit_code'], 2)

    def test_allowed_failure_and_baseline_gates(self):
        with mock.patch('devpocket.workspace.invoke', side_effect=lambda tool, *a: result(tool, True)):
            first = check(self.root, fail_on='none')
            source, baseline = self.root / 'first.json', self.root / 'baseline.json'
            source.write_text(json.dumps(first))
            create_baseline(source, baseline)
            second = check(self.root, baseline=baseline)
        self.assertEqual(first['exit_code'], 0)
        self.assertEqual(second['exit_code'], 0)
        self.assertEqual(len(second['findings']), 3)
        self.assertEqual(second['baseline']['new'], 0)
        self.assertEqual(len({f['fingerprint'] for f in second['findings']}), 3)
        self.assertEqual(second['findings'][1]['path'], 'apps/web/file.py')
        self.assertEqual(second['findings'][1]['check'], 'web/scan')

    def test_relocation_does_not_mutate_cached_worker_reports(self):
        raw = result(finding=True)
        original = copy.deepcopy(raw)
        with mock.patch('devpocket.workspace.invoke', return_value=raw): check(self.root)
        self.assertEqual(raw, original)

    def test_report_budget_cancels_and_fails_even_with_allowed_failure(self):
        (self.root / 'packages/lib/.devpocket.json').write_text(json.dumps({'version': 1, 'checks': {'scan': {'tool': 'envtwin', 'allow_failure': True}}}))
        calls = []
        def worker(tool, *args):
            calls.append(args[-2])
            return result(tool)
        with mock.patch('devpocket.workspace.MAX_REPORT', 262145), mock.patch('devpocket.workspace.invoke', side_effect=worker):
            report = check(self.root, jobs=1)
        self.assertEqual(report['exit_code'], 2)
        self.assertTrue(calls[0].is_set())
        self.assertEqual(len(calls), 1)

    def test_explicit_allowed_failure_unblocks_project(self):
        (self.root / 'packages/lib/.devpocket.json').write_text(json.dumps({'version': 1, 'checks': {'scan': {'tool': 'envtwin', 'allow_failure': True}}}))
        def worker(tool, params, root, *args):
            return failure(tool, 'Allowed fixture failure') if root.name == 'lib' else result(tool)
        with mock.patch('devpocket.workspace.invoke', side_effect=worker): report = check(self.root)
        self.assertEqual([s['status'] for s in report['checks']], ['allowed_failure', 'passed', 'passed'])
        self.assertEqual(report['exit_code'], 0)

    def test_interruption_signals_cleanup(self):
        signals = []
        def worker(tool, *args):
            signals.append(args[-2])
            raise KeyboardInterrupt()
        with mock.patch('devpocket.workspace.invoke', side_effect=worker):
            with self.assertRaises(KeyboardInterrupt): check(self.root, jobs=1)
        self.assertTrue(signals[0].is_set())

    def test_cache_stays_project_local_and_no_cache_forces_fresh_work(self):
        project = self.root / 'apps/api'
        (project / 'events.log').write_text('INFO request completed\n')
        (project / '.devpocket.json').write_text(json.dumps({'version': 1, 'checks': {'logs': {'tool': 'loglens', 'input': {'paths': ['events.log']}, 'cache': {'inputs': ['events.log']}}}}))
        first = check(self.root, projects=['api'])
        second = check(self.root, projects=['api'])
        fresh = check(self.root, projects=['api'], use_cache=False)
        for report in (first, second, fresh): self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(first['checks'][0]['report']['cache']['status'], 'miss')
        self.assertEqual(second['checks'][0]['report']['cache']['status'], 'hit')
        self.assertEqual(fresh['checks'][0]['report']['cache']['status'], 'bypass')
        self.assertTrue((project / '.devpocket/cache-v1').is_dir())
        self.assertFalse((self.root / '.devpocket').exists())

    def test_empty_selection_is_explicit_in_sarif(self):
        report = check(self.root, changed=[])
        self.assertEqual(report['checks'], [])
        properties = sarif(report)['runs'][0]['invocations'][0]['properties']
        self.assertEqual(properties['workspaceScope'], 'selected')
        self.assertEqual(properties['selectedProjects'], [])
        self.assertEqual(len(properties['unselectedProjects']), 3)

    def test_real_worker_sdk_and_cli_plan(self):
        report = check(self.root, projects=['api'])
        self.assertEqual(report['exit_code'], 0, report)
        report = execute('workspace-plan', {'changed_files': ['apps/api/new.py']}, self.root)
        self.assertEqual(report['status'], 'completed', report)
        self.assertEqual(report['data']['nodes'][0]['name'], 'api/scan')
        code, output, error = self.cli(['workspace', 'plan', '--root', str(self.root), '--format', 'json'])
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)['tool'], 'workspace-plan')

    def test_execution_stays_explicit(self):
        path = self.root / 'apps/api/.devpocket.json'
        path.write_text(json.dumps({'version': 1, 'checks': {'run': {'tool': 'oopsfile', 'input': {'command': ['unrequested-command'], 'output': 'out.md'}}}}))
        report = check(self.root, projects=['api'])
        self.assertEqual(report['exit_code'], 2)
        self.assertIn('--allow-exec', report['checks'][0]['report']['summary'])


if __name__ == '__main__':
    unittest.main()
