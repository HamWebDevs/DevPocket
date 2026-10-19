"""Stable configuration surfaces, safe Action boundaries and bounded aggregation."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from devpocket import __version__
from devpocket import checks, configuration, reports
from devpocket.common import load_json
from devpocket.engine import execute
from devpocket.sdk import Finding
from test_platform import TempTest

location = Path(__file__).resolve().parents[1] / '.github/action.py'
spec = importlib.util.spec_from_file_location('action_driver', location)
action = importlib.util.module_from_spec(spec)
spec.loader.exec_module(action)


def envelope(finding=False):
    return {'schema': 1, 'version': __version__, 'tool': 'envtwin', 'status': 'completed', 'exit_code': 0, 'summary': 'ready', 'findings': [Finding('issue', 'Review this').as_dict()] if finding else [], 'data': {}}


class ConfigurationTests(TempTest):
    def save(self, checks=None, **fields):
        path = self.root / '.devpocket.json'
        path.write_text(json.dumps({'version': 1, 'checks': checks if checks is not None else {'env': {'tool': 'envtwin'}}, **fields}))
        return path

    def test_preflight_and_schema_hint_never_fetch_or_run_checks(self):
        self.save(**{'$schema': 'https://example.invalid/not-fetched.json'})
        with mock.patch('devpocket.checks.invoke') as worker:
            report = execute('config-validate', {}, self.root)
        worker.assert_not_called()
        self.assertTrue(report['data']['configuration_valid'])
        self.assertFalse(report['data']['checks_executed'])

    def test_missing_disabled_and_conflicting_plugins_are_errors(self):
        for plugins in ([], ['fixture']):
            self.save({'test': {'tool': 'fixture'}}, plugins=plugins)
            report = configuration.inspect(self.root)
            self.assertFalse(report.data['configuration_valid'])

    def test_metadata_discovery_does_not_import_enabled_plugin(self):
        self.save({'test': {'tool': 'fixture', 'input': {'private': 'PRIVATE_FIXTURE'}}}, plugins=['fixture'])
        entry = SimpleNamespace(name='fixture', dist=None, load=mock.Mock(side_effect=AssertionError('imported plugin')))
        with mock.patch('devpocket.registry.metadata.entry_points', return_value=[entry]):
            report = configuration.inspect(self.root)
        self.assertTrue(report.data['configuration_valid'])
        self.assertEqual(report.data['plugin_inputs_unverified'], 1)
        self.assertNotIn('PRIVATE_FIXTURE', str(report))
        entry.load.assert_not_called()

    def test_builtin_parameter_errors_are_located_without_echoing_inputs(self):
        self.save({'test': {'tool': 'importdoctor', 'input': {'unexpected': 'PRIVATE_FIXTURE'}}})
        report = configuration.inspect(self.root)
        self.assertFalse(report.data['configuration_valid'])
        self.assertEqual(report.findings[0].path, '.devpocket.json')
        self.assertNotIn('PRIVATE_FIXTURE', str(report))

    def test_empty_and_missing_configs_do_not_certify_checks(self):
        with self.assertRaises(ValueError): configuration.inspect(self.root)
        self.save({})
        self.assertFalse(configuration.inspect(self.root).data['configuration_valid'])
        (self.root / '.devpocket.json').write_text('{"version":1}')
        self.assertFalse(configuration.inspect(self.root).data['configuration_valid'])

    def test_workspace_preflight_uses_each_projects_plugin_scope(self):
        (self.root / 'a').mkdir()
        (self.root / 'a/.devpocket.json').write_text(json.dumps({'version': 1, 'checks': {'check': {'tool': 'envtwin'}}}))
        (self.root / '.devpocket-workspace.json').write_text(json.dumps({'$schema': 'https://example.invalid/workspace', 'version': 1, 'projects': {'a': {'path': 'a'}}}))
        report = configuration.inspect(self.root, workspace=True)
        self.assertTrue(report.data['configuration_valid'])
        self.assertEqual(report.data['checks'], 1)
        self.assertEqual(len(report.data['plan_sha256']), 64)

    def test_cli_preflight_formats_and_output_collision(self):
        self.save()
        code, output, _ = self.cli(['config', 'validate', '--root', str(self.root), '--format', 'sarif'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['version'], '2.1.0')
        target = self.root / 'schema.json'
        code, _, _ = self.cli(['config', 'schema', '--kind', 'workspace', '--output', str(target)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(target.read_text())['properties']['version']['const'], 1)
        with mock.patch('devpocket.configuration.inspect') as inspector:
            code, _, _ = self.cli(['config', 'validate', '--root', str(self.root), '--output', str(target)])
        self.assertEqual(code, 2)
        inspector.assert_not_called()

    def test_radar_runner_exemptions_are_limited_to_known_ci_names_and_paths(self):
        from devpocket.reporadar import scan
        (self.root / '.github').mkdir()
        (self.root / '.github/check.py').write_text("import os\na=os.environ['GITHUB_WORKSPACE']\nb=os.environ['CUSTOM_CI_SECRET']\n")
        (self.root / 'app.py').write_text("import os\na=os.environ['GITHUB_WORKSPACE']\n")
        findings = [f for f in scan(self.root) if f['code'] == 'undocumented-env']
        self.assertEqual({f['path'] for f in findings}, {'.github/check.py', 'app.py'})
        self.assertEqual(len(findings), 2)


class AggregationTests(TempTest):
    def test_baseline_is_read_once_and_is_stable_during_execution(self):
        path = self.root / 'accepted.json'
        finding = envelope(True)['findings'][0]
        path.write_text(json.dumps({'schema': 1, 'fingerprints': ['envtwin:' + finding['fingerprint']]}))
        config = {'version': 1, 'checks': {'a': {'tool': 'envtwin'}, 'b': {'tool': 'envtwin', 'needs': ['a']}}}
        def worker(*args):
            path.write_text('changed after preflight')
            return envelope(True)
        with mock.patch('devpocket.reports.load_json', wraps=load_json) as reader, mock.patch('devpocket.checks.invoke', side_effect=worker):
            result = checks.pipeline(config, self.root, baseline=path)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['baseline']['existing'], 2)

    def test_resource_exhaustion_cancels_and_cannot_be_allowed_to_fail(self):
        events = []
        def worker(*args):
            events.append(args[-2])
            return envelope()
        config = {'version': 1, 'checks': {'a': {'tool': 'envtwin', 'allow_failure': True}, 'b': {'tool': 'envtwin', 'needs': ['a']}}}
        with mock.patch.object(checks, 'MAX_REPORT', 262145), mock.patch.object(checks, 'invoke', side_effect=worker):
            result = checks.pipeline(config, self.root, jobs=1)
        self.assertEqual(result['exit_code'], 2)
        self.assertEqual([s['status'] for s in result['checks']], ['failed', 'skipped'])
        self.assertTrue(events[0].is_set())

    def test_bounded_reads_and_nonfinite_json(self):
        path = self.root / 'data.json'
        path.write_text('{"value":NaN}')
        with self.assertRaises(ValueError): load_json(path)
        path.write_text(' ' * 20)
        with self.assertRaises(ValueError): load_json(path, max_bytes=16)
        with self.assertRaises(ValueError): load_json(self.root)

    def test_baseline_resource_limits_and_boolean_jobs(self):
        path = self.root / 'data.json'
        path.write_text(json.dumps({'schema': 1, 'fingerprints': ['x' * 257]}))
        with self.assertRaises(ValueError): reports.read_baseline(path)
        with self.assertRaises(ValueError): checks.pipeline({'version': 1, 'checks': {}}, self.root, jobs=True)


class ActionTests(TempTest):
    def setUp(self):
        super().setUp()
        self.checkout = self.root / 'checkout'
        self.checkout.mkdir()
        self.runner = self.root / 'runner'
        self.runner.mkdir()
        self.config = self.checkout / '.devpocket.json'
        self.config.write_text(json.dumps({'version': 1, 'checks': {'env': {'tool': 'envtwin'}}}))
        self.environ = {'GITHUB_WORKSPACE': str(self.checkout), 'RUNNER_TEMP': str(self.runner), 'GITHUB_OUTPUT': str(self.root / 'outputs'), 'GITHUB_STEP_SUMMARY': str(self.root / 'summary')}
        patch = mock.patch.dict(os.environ, self.environ, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_action_validates_all_inputs_before_installation(self):
        for key, bad in [('DEVPOCKET_MODE', 'shell'), ('DEVPOCKET_ALLOW_EXEC', 'yes'), ('DEVPOCKET_JOBS', '4;echo bad'), ('DEVPOCKET_ROOT', '../escape'), ('DEVPOCKET_ROOT', 'a\n::error::bad')]:
            with mock.patch.dict(os.environ, {key: bad}):
                with self.assertRaises(ValueError): action.inputs()

    def test_annotations_escape_data_and_properties(self):
        self.assertEqual(action.escape('a%\n::error::fake'), 'a%25%0A::error::fake')
        self.assertEqual(action.escape('a,b:c\r', True), 'a%2Cb%3Ac%0D')

    def test_literal_shell_characters_in_config_are_never_executed(self):
        name = 'checks$(touch PWN).json'
        (self.checkout / name).write_text(self.config.read_text())
        with mock.patch.dict(os.environ, {'DEVPOCKET_CONFIG': name}):
            options = action.inputs()
        self.assertEqual(options['config'].name, name)
        self.assertFalse((self.checkout / 'PWN').exists())

    def test_real_action_run_writes_reports_outputs_and_summary(self):
        options = action.inputs()
        with contextlib.redirect_stdout(io.StringIO()): code = action.run(options)
        self.assertEqual(code, 0)
        values = dict(line.split('=', 1) for line in Path(self.environ['GITHUB_OUTPUT']).read_text().splitlines())
        self.assertEqual(values['exit-code'], '0')
        self.assertEqual(json.loads(Path(values['report']).read_text())['checks'][0]['status'], 'passed')
        self.assertEqual(json.loads(Path(values['sarif']).read_text())['version'], '2.1.0')
        self.assertIn('Gate status: 0', Path(self.environ['GITHUB_STEP_SUMMARY']).read_text())

    def test_failed_preflight_emits_complete_artifacts_without_running_workers(self):
        self.config.write_text(json.dumps({'version': 1, 'checks': {'bad': {'tool': 'missing-plugin'}}}))
        with mock.patch('devpocket.checks.invoke') as worker, contextlib.redirect_stdout(io.StringIO()):
            code = action.run(action.inputs())
        self.assertEqual(code, 1)
        worker.assert_not_called()
        values = dict(line.split('=', 1) for line in Path(self.environ['GITHUB_OUTPUT']).read_text().splitlines())
        self.assertEqual(values['exit-code'], '1')
        self.assertEqual(json.loads(Path(values['report']).read_text())['tool'], 'config-validate')

    def test_annotations_are_bounded_and_existing_debt_is_not_reannounced(self):
        report = envelope(True)
        report['findings'] *= 100
        report['findings'].append({**Finding('known', 'Accepted debt').as_dict(), 'existing': True})
        directory = self.runner / 'reports'
        directory.mkdir()
        output = io.StringIO()
        with contextlib.redirect_stdout(output): action.publish(report, self.checkout, directory)
        self.assertEqual(output.getvalue().count('::warning'), 50)
        self.assertNotIn('Accepted debt', output.getvalue())
        self.assertEqual(len(json.loads((directory / 'report.json').read_text())['findings']), 101)

    def test_long_annotation_messages_do_not_flood_logs_or_truncate_artifacts(self):
        report = envelope()
        report['findings'] = [Finding('long', 'x' * 10000).as_dict()]
        directory = self.runner / 'reports'
        directory.mkdir()
        output = io.StringIO()
        with contextlib.redirect_stdout(output): action.publish(report, self.checkout, directory)
        self.assertLess(len(output.getvalue()), 5000)
        self.assertEqual(len(json.loads((directory / 'report.json').read_text())['findings'][0]['message']), 10000)


if __name__ == '__main__': unittest.main()
