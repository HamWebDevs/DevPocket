"""Public SDK, process boundaries, pipelines, reports and MCP contract tests."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from devpocket import __version__
from devpocket.checks import invoke, pipeline
from devpocket.cli import main
from devpocket.engine import execute, gated_exit
from devpocket.mcp_server import Server
from devpocket.project import init, load, validate
from devpocket.registry import Registry
from devpocket.reports import apply_baseline, create_baseline, sarif
from devpocket.scaffold import scaffold
from devpocket.sdk import Finding, ToolContext, ToolResult, ToolSpec, validate_input


def spec(name='example', runner=None, read_only=True):
    return ToolSpec(name, 'Example diagnostic', {'type': 'object', 'properties': {}, 'additionalProperties': False}, runner or (lambda ctx, params: ToolResult('ok')), read_only=read_only)


class TempTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()


class SDKTests(TempTest):
    def test_fingerprint_survives_line_moves(self):
        a = Finding('rule', 'same message', path='a.py', line=1).as_dict()
        b = Finding('rule', 'same message', path='a.py', line=99).as_dict()
        self.assertEqual(a['fingerprint'], b['fingerprint'])
        self.assertNotEqual(a['fingerprint'], Finding('rule', 'different message', path='a.py').as_dict()['fingerprint'])

    def test_invalid_finding_locations(self):
        for path in ('../outside', '/absolute', 'C:/absolute', 'a\\b'):
            with self.assertRaises(ValueError):
                Finding('rule', 'message', path=path)
        with self.assertRaises(ValueError):
            Finding('rule', 'message', line=0)

    def test_redaction_handles_long_unbroken_output(self):
        from devpocket.common import run
        result = run([sys.executable, '-c', "from devpocket.common import redact; assert redact('x'*500000)=='x'*500000"], timeout=5)
        self.assertEqual(result['returncode'], 0, result['stderr'])

    def test_root_containment_and_escaped_symlink(self):
        with self.assertRaises(ValueError):
            ToolContext(self.root).resolve('../outside')
        if os.name == 'posix':
            (self.root / 'outside').symlink_to(self.root.parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                ToolContext(self.root).resolve('outside/file')

    def test_schema_rejects_unknown_keys_and_boolean_integers(self):
        schema = {'type': 'object', 'properties': {'count': {'type': 'integer', 'minimum': 1}}, 'required': ['count'], 'additionalProperties': False}
        for value in ({}, {'count': True}, {'count': 0}, {'count': 1, 'extra': 2}):
            with self.assertRaises(ValueError):
                validate_input(value, schema)
        validate_input({'count': 1}, schema)

    def test_unsupported_schema_and_api_rejected(self):
        with self.assertRaises(ValueError):
            ToolSpec('x', 'description', {'type': 'object', '$ref': 'nope'}, lambda a, b: None)
        with self.assertRaises(ValueError):
            ToolSpec('x', 'description', {'type': 'object'}, lambda a, b: None, api_version=99)

    def test_plugin_stdout_is_captured_and_redacted(self):
        def runner(ctx, params):
            print('token=hidden-secret')
            return ToolResult('ready', data={'api_key': 'never-export', 'message': 'password=do-not-show'})
        registry = SimpleNamespace(get=lambda name: spec(runner=runner))
        result = execute('example', {}, self.root, registry=registry)
        text = json.dumps(result)
        for secret in ('hidden-secret', 'never-export', 'do-not-show'):
            self.assertNotIn(secret, text)
        self.assertEqual(result['status'], 'completed')
        self.assertIn('diagnostics', result)

    def test_result_size_and_invalid_json_values_fail_cleanly(self):
        for payload in ({'large': 'x' * (2 * 1024 * 1024)}, {'bad': object()}, {'bad': float('nan')}):
            registry = SimpleNamespace(get=lambda name: spec(runner=lambda c, p: ToolResult('test', data=payload)))
            self.assertEqual(execute('example', {}, self.root, registry=registry)['status'], 'error')

    def test_non_readonly_tools_need_execution_optin(self):
        runner = mock.Mock(return_value=ToolResult('done'))
        registry = SimpleNamespace(get=lambda name: spec(runner=runner, read_only=False))
        self.assertEqual(execute('example', {}, self.root, registry=registry)['status'], 'error')
        runner.assert_not_called()
        self.assertEqual(execute('example', {}, self.root, registry=registry, allow_exec=True)['status'], 'completed')

    def test_discovery_does_not_import_plugins(self):
        entry = SimpleNamespace(name='my-check', dist=None, load=mock.Mock(side_effect=RuntimeError('must not load')))
        with mock.patch('devpocket.registry.metadata.entry_points', return_value=[entry]):
            registry = Registry()
            self.assertIn('my-check', {r['name'] for r in registry.inventory()})
            with self.assertRaises(ValueError):
                registry.get('my-check')
        entry.load.assert_not_called()

    def test_plugins_are_loaded_only_when_enabled_and_used(self):
        factory = mock.Mock(return_value=spec('my-check'))
        entry = SimpleNamespace(name='my-check', dist=None, load=mock.Mock(return_value=factory))
        with mock.patch('devpocket.registry.metadata.entry_points', return_value=[entry]):
            registry = Registry(['my-check'])
            registry.inventory()
            entry.load.assert_not_called()
            self.assertIs(registry.get('my-check'), registry.get('my-check'))
        factory.assert_called_once()

    def test_duplicate_plugins_cannot_be_run(self):
        entry = SimpleNamespace(name='my-check', dist=None, load=mock.Mock())
        with mock.patch('devpocket.registry.metadata.entry_points', return_value=[entry, entry]):
            with self.assertRaises(ValueError):
                Registry(['my-check']).get('my-check')
        entry.load.assert_not_called()

    def test_worker_runs_builtin_and_blocks_escape(self):
        (self.root / 'README.md').write_text('readme')
        report = invoke('reporadar', {}, self.root)
        self.assertEqual(report['status'], 'completed')
        report = invoke('loglens', {'paths': ['../outside.log']}, self.root)
        self.assertEqual(report['status'], 'error')

    @unittest.skipUnless(os.name == 'posix', 'POSIX process-group cleanup')
    def test_worker_timeout_cleans_up_wrapped_command(self):
        marker = self.root / 'orphan-marker'
        script = "import time;from pathlib import Path;time.sleep(1);Path('orphan-marker').write_text('leaked')"
        report = invoke('oopsfile', {'command': [sys.executable, '-c', script], 'output': 'failure.md', 'timeout': 5}, self.root, allow_exec=True, timeout=.25)
        self.assertEqual(report['status'], 'error')
        time.sleep(1.1)
        self.assertFalse(marker.exists())

    def test_scaffold_is_complete_and_refuses_overwrite(self):
        target = scaffold(self.root / 'plugin', 'long-lines')
        self.assertTrue((target / 'pyproject.toml').exists())
        code = (target / 'devpocket_plugin_long_lines/__init__.py').read_text()
        compile(code, 'plugin', 'exec')
        with self.assertRaises(ValueError):
            scaffold(target, 'long-lines')
        with self.assertRaises(ValueError):
            scaffold(self.root / 'bad', 'reporadar')


class PipelineTests(TempTest):
    def test_init_does_not_overwrite(self):
        init(self.root)
        self.assertIn('repository', load(self.root)['checks'])
        with self.assertRaises(FileExistsError):
            init(self.root)

    def test_cycles_unknown_dependencies_and_versions_rejected(self):
        for config in ({'version': True}, {'version': 1, 'checks': {'a': {'tool': 'reporadar', 'needs': ['b']}}}, {'version': 1, 'checks': {'a': {'tool': 'reporadar', 'needs': ['b']}, 'b': {'tool': 'reporadar', 'needs': ['a']}}}):
            with self.assertRaises(ValueError):
                validate(config)

    def test_explicit_missing_config_is_an_error(self):
        with self.assertRaises(ValueError):
            load(self.root, self.root / 'missing.json')

    def test_baseline_never_hides_execution_failures(self):
        report = {'status': 'failed', 'exit_code': 7, 'findings': [{'severity': 'error', 'existing': True}]}
        self.assertEqual(gated_exit(report, 'none'), 1)

    def test_dependencies_and_failure_skip(self):
        config = {'version': 1, 'checks': {'first': {'tool': 'reporadar'}, 'next': {'tool': 'envtwin', 'needs': ['first']}}}
        report = pipeline(config, self.root)
        self.assertEqual([s['status'] for s in report['checks']], ['failed', 'skipped'])
        self.assertEqual(report['exit_code'], 1)

    def test_allowed_failure_does_not_block_dependents(self):
        config = {'version': 1, 'checks': {'first': {'tool': 'reporadar', 'allow_failure': True}, 'next': {'tool': 'envtwin', 'needs': ['first']}}}
        report = pipeline(config, self.root)
        self.assertEqual([s['status'] for s in report['checks']], ['allowed_failure', 'passed'])
        self.assertEqual(report['exit_code'], 0)

    def test_independent_checks_are_concurrent(self):
        barrier = threading.Barrier(2, timeout=3)
        def fake(tool, *a):
            barrier.wait()
            return {'schema': 1, 'version': __version__, 'tool': tool, 'summary': 'ready', 'status': 'completed', 'exit_code': 0, 'findings': [], 'data': {}}
        config = {'version': 1, 'checks': {'a': {'tool': 'envtwin'}, 'b': {'tool': 'envtwin'}}}
        with mock.patch('devpocket.checks.invoke', side_effect=fake):
            result = pipeline(config, self.root, jobs=2)
        self.assertEqual(result['exit_code'], 0)

    def test_finding_baseline_allows_old_debt(self):
        result = invoke('reporadar', {}, self.root)
        source, baseline = self.root / 'report.json', self.root / 'baseline.json'
        source.write_text(json.dumps(result))
        create_baseline(source, baseline)
        self.assertEqual(gated_exit(apply_baseline(result, baseline)), 0)
        result['findings'].append(Finding('new-problem', 'new problem', severity='error').as_dict())
        self.assertEqual(gated_exit(apply_baseline(result, baseline)), 1)

    def test_sarif_locations_and_baseline_state(self):
        finding = Finding('rule', 'message', path='folder/file name.py', line=4).as_dict()
        finding['existing'] = True
        result = sarif({'tool': 'example', 'version': __version__, 'status': 'completed', 'findings': [finding]})['runs'][0]['results'][0]
        self.assertEqual(result['level'], 'warning')
        self.assertEqual(result['locations'][0]['physicalLocation']['artifactLocation']['uri'], 'folder/file%20name.py')
        self.assertEqual(result['baselineState'], 'unchanged')

    def test_existing_output_aborts_before_execution(self):
        output = self.root / 'already.json'
        output.write_text('existing')
        with mock.patch('devpocket.platform_cli.invoke') as invoke_mock:
            code, _, _ = self.cli(['run', 'reporadar', '--root', str(self.root), '--output', str(output)])
        self.assertEqual(code, 2)
        invoke_mock.assert_not_called()

    def test_run_and_check_json_contract(self):
        (self.root / '.devpocket.json').write_text(json.dumps({'version': 1, 'checks': {'environment': {'tool': 'envtwin'}}}))
        code, output, _ = self.cli(['check', '--root', str(self.root), '--format', 'json'])
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)['tool'], 'check')


class MCPTests(TempTest):
    def handshake(self, server):
        server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}})
        server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def test_default_tool_list_excludes_execution(self):
        output = io.StringIO()
        server = Server(self.root, output=output)
        self.handshake(server)
        server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        server.executor.shutdown()
        tools = json.loads(output.getvalue().splitlines()[-1])['result']['tools']
        self.assertEqual({t['name'] for t in tools}, {'assetguard', 'reporadar', 'envtwin', 'loglens', 'importdoctor', 'workspace-plan', 'config-validate'})

    def test_preinitialization_and_unknown_tool_are_protocol_errors(self):
        output = io.StringIO()
        server = Server(self.root, output=output)
        server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        self.handshake(server)
        server.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'undorun'}})
        server.handle({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': []}})
        server.executor.shutdown()
        rows = [json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual(rows[0]['error']['code'], -32002)
        self.assertEqual(rows[-1]['error']['code'], -32602)

    def test_malformed_json_does_not_destroy_session(self):
        output = io.StringIO()
        server = Server(self.root, output=output)
        server.serve(io.StringIO('{invalid\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n'))
        rows = [json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual(rows[0]['error']['code'], -32700)
        self.assertEqual(rows[1]['result'], {})

    def test_cancellation_sets_worker_event_and_suppresses_response(self):
        output = io.StringIO()
        server = Server(self.root, output=output)
        self.handshake(server)
        entered = threading.Event()
        def fake(*a, **kw):
            entered.set()
            self.assertTrue(kw['cancel_event'].wait(3))
            return {'status': 'error'}
        with mock.patch('devpocket.mcp_server.invoke', side_effect=fake):
            server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'envtwin'}})
            self.assertTrue(entered.wait(3))
            server.handle({'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': 2}})
            server.executor.shutdown(wait=True)
        self.assertEqual(len(output.getvalue().splitlines()), 1)

    def test_real_stdio_tool_roundtrip(self):
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'fixture', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'importdoctor', 'arguments': {'module': 'json'}}},
        ]
        result = subprocess.run([sys.executable, '-m', 'devpocket', 'serve', '--root', str(self.root)], input=''.join(json.dumps(m) + '\n' for m in messages), text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {row['id']: row for row in map(json.loads, result.stdout.splitlines())}
        self.assertFalse(rows[2]['result']['isError'])
        self.assertTrue(rows[2]['result']['structuredContent']['data']['resolution']['found'])

if __name__ == '__main__':
    unittest.main()
