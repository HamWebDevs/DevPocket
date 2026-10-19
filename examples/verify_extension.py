"""Build/install host and generated plugin in a fresh venv; verify every integration.

Runs only on explicit invocation. No user checkout is modified. Build dependencies
may be downloaded from the configured Python package registry unless
--no-build-isolation is used with setuptools and wheel already installed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def command(argv, *, cwd=None, expected=0, input=None):
    result = subprocess.run([str(a) for a in argv], cwd=cwd, text=True, input=input, capture_output=True, timeout=120)
    if result.returncode != expected:
        raise AssertionError(f"Command failed ({result.returncode}): {argv}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-build-isolation', action='store_true')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        wheels, project, plugin = root / 'wheels', root / 'project', root / 'plugin'
        wheels.mkdir()
        project.mkdir()
        build_flags = ['--no-build-isolation'] if args.no_build_isolation else []
        command([sys.executable, '-m', 'pip', 'wheel', '--no-deps', *build_flags, '--wheel-dir', wheels, source])
        command([sys.executable, '-m', 'devpocket', 'plugins', 'scaffold', plugin, '--name', 'long-lines'], cwd=source)
        marker = project / 'plugin-was-loaded'
        module = plugin / 'devpocket_plugin_long_lines' / '__init__.py'
        module.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ").write_text('loaded')\n" + module.read_text())
        command([sys.executable, '-m', 'pip', 'wheel', '--no-deps', *build_flags, '--wheel-dir', wheels, plugin])
        # Frozen pre-cache API v1 factory: no optional cache field is supplied.
        legacy = root / 'legacy'
        legacy.mkdir()
        (legacy / 'legacy_contract').mkdir()
        (legacy / 'pyproject.toml').write_text('''[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"
[project]
name = "devpocket-legacy-contract"
version = "0.1.0"
dependencies = ["devpocket-toolkit>=0.3,<2"]
[project.entry-points."devpocket.tools"]
legacy-v1 = "legacy_contract:build_tool"
''')
        (legacy / 'legacy_contract/__init__.py').write_text('''from devpocket.sdk import Finding, ToolResult, ToolSpec
def run(context, params):
    return ToolResult("Legacy API v1", [Finding("legacy-note", "Pre-cache contract still works", severity="note")], {"contract": 1})
def build_tool():
    return ToolSpec("legacy-v1", "Frozen API v1 fixture", {"type": "object", "properties": {}, "additionalProperties": False}, run, read_only=True, api_version=1)
''')
        command([sys.executable, '-m', 'pip', 'wheel', '--no-deps', *build_flags, '--wheel-dir', wheels, legacy])
        environment = root / 'venv'
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        command([python, '-m', 'pip', 'install', '--no-index', '--find-links', wheels, 'devpocket-toolkit', 'devpocket-tool-long-lines', 'devpocket-legacy-contract'])
        cli = [python, '-m', 'devpocket']
        command([*cli, 'plugins', 'enable', 'legacy-v1', '--root', project], cwd=project)
        legacy_result = json.loads(command([*cli, 'run', 'legacy-v1', '--root', project, '--format', 'json'], cwd=project))
        assert legacy_result['data']['contract'] == 1
        assert legacy_result['findings'][0]['severity'] == 'note'
        inventory = json.loads(command([*cli, 'plugins', 'list', '--root', project, '--json'], cwd=project))
        assert any(x['name'] == 'long-lines' and not x['enabled'] for x in inventory)
        assert not marker.exists(), 'Discovery imported plugin code'
        payload = json.dumps({'path': 'sample.txt', 'max_length': 5})
        (project / 'sample.txt').write_text('abcdefghij\n')
        command([*cli, 'run', 'long-lines', '--root', project, '--input', payload, '--format', 'json'], cwd=project, expected=2)
        assert not marker.exists(), 'Disabled plugin was loaded'
        command([*cli, 'plugins', 'enable', 'long-lines', '--root', project], cwd=project)
        assert not marker.exists(), 'Enabling imported plugin code'
        report = command([*cli, 'run', 'long-lines', '--root', project, '--input', payload, '--format', 'json'], cwd=project, expected=1)
        assert marker.exists()
        assert len(json.loads(report)['findings']) == 1
        report_path, baseline = project / 'result.json', project / 'baseline.json'
        report_path.write_text(report)
        command([*cli, 'baseline', '--from', report_path, '--output', baseline], cwd=project)
        command([*cli, 'run', 'long-lines', '--root', project, '--input', payload, '--baseline', baseline], cwd=project)
        config = {'version': 1, 'plugins': ['long-lines'], 'checks': {'lines': {'tool': 'long-lines', 'input': json.loads(payload), 'cache': {'inputs': ['sample.txt']}}, 'imports': {'tool': 'importdoctor', 'input': {'module': 'json'}, 'needs': ['lines']}}}
        (project / '.devpocket.json').write_text(json.dumps(config))
        checks = json.loads(command([*cli, 'check', '--root', project, '--baseline', baseline, '--format', 'json'], cwd=project))
        assert checks['exit_code'] == 0
        assert checks['checks'][0]['report']['cache']['status'] == 'miss'
        reused = json.loads(command([*cli, 'check', '--root', project, '--baseline', baseline, '--format', 'json'], cwd=project))
        assert reused['checks'][0]['report']['cache']['status'] == 'hit'
        fresh = json.loads(command([*cli, 'check', '--root', project, '--baseline', baseline, '--format', 'json', '--no-cache'], cwd=project))
        assert fresh['checks'][0]['report']['cache']['status'] == 'bypass'
        (project / 'sample.txt').write_text('short\n')
        changed = json.loads(command([*cli, 'check', '--root', project, '--format', 'json'], cwd=project))
        assert changed['checks'][0]['report']['cache']['status'] == 'miss'
        assert not changed['checks'][0]['report']['findings']
        (project / 'sample.txt').write_text('abcdefghij\n')
        cleared = json.loads(command([*cli, 'cache', 'clear', '--root', project, '--json'], cwd=project))
        assert cleared['removed'] >= 2
        sarif = json.loads(command([*cli, 'run', 'long-lines', '--root', project, '--input', payload, '--baseline', baseline, '--format', 'sarif'], cwd=project))
        assert sarif['runs'][0]['results'][0]['baselineState'] == 'unchanged'
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'extension-test', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'long-lines', 'arguments': json.loads(payload)}},
        ]
        output = command([*cli, 'serve', '--root', project, '--plugin', 'long-lines'], cwd=project, input=''.join(json.dumps(x) + '\n' for x in messages))
        replies = {row['id']: row for row in map(json.loads, output.splitlines())}
        assert 'long-lines' in {x['name'] for x in replies[2]['result']['tools']}
        assert len(replies[3]['result']['structuredContent']['findings']) == 1
        assert not replies[3]['result']['isError']
        command([python, '-m', 'unittest', 'discover', '-v'], cwd=plugin)
        print('Extension verification passed: frozen pre-cache API v1 compatibility, real wheels, metadata-only discovery, enable/disable boundary, baseline, cached checks, invalidation, SARIF, MCP and generated plugin tests.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
