"""Composite action entry point; workflow inputs never become shell source."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import venv


def relative(base, value, *, directory=False):
    if not value or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value) or '\\' in value or ':' in value:
        raise ValueError('Action paths must be printable checkout-relative POSIX paths')
    from pathlib import PurePosixPath
    parts = PurePosixPath(value)
    if parts.is_absolute() or '..' in parts.parts or parts.as_posix() != value:
        raise ValueError('Action paths must remain beneath the selected root')
    target = base / value
    for parent in (target, *target.parents):
        if parent == base: break
        if parent.is_symlink(): raise ValueError('Action paths cannot traverse symlinks')
    if not target.resolve().is_relative_to(base): raise ValueError('Action path leaves its root')
    if directory and not target.is_dir(): raise ValueError('Action root does not exist')
    if not directory and not target.is_file(): raise ValueError('Action input file does not exist')
    return target.resolve()


def inputs():
    checkout = Path(os.environ['GITHUB_WORKSPACE']).resolve()
    root = relative(checkout, os.environ.get('DEVPOCKET_ROOT', '.'), directory=True)
    mode = os.environ.get('DEVPOCKET_MODE', 'project')
    level = os.environ.get('DEVPOCKET_FAIL_ON', 'warning')
    execution = os.environ.get('DEVPOCKET_ALLOW_EXEC', 'false')
    raw_jobs = os.environ.get('DEVPOCKET_JOBS', '4')
    if mode not in {'project', 'workspace'} or level not in {'error', 'warning', 'none'} or execution not in {'true', 'false'} or not re.fullmatch('[1-8]', raw_jobs):
        raise ValueError('Invalid action mode, gate, allow-exec boolean or jobs limit')
    result = {'root': root, 'mode': mode, 'fail_on': level, 'allow_exec': execution == 'true', 'jobs': int(raw_jobs)}
    for key, base, default in (('config', root, '.devpocket-workspace.json' if mode == 'workspace' else '.devpocket.json'), ('baseline', root, ''), ('requirements', checkout, '')):
        value = os.environ.get('DEVPOCKET_' + key.upper(), '') or default
        result[key] = relative(base, value) if value else None
    return result


def escape(value, property=False):
    result = str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    return result.replace(':', '%3A').replace(',', '%2C') if property else result


def annotation(value):
    value = str(value)
    return escape(value if len(value) <= 4096 else value[:4050] + ' ... [see complete report]')


def publish(report, root, directory):
    from devpocket.common import write_text
    from devpocket.reports import render
    paths = {'report': directory / 'report.json', 'sarif': directory / 'report.sarif'}
    write_text(paths['report'], render(report, 'json'))
    write_text(paths['sarif'], render(report, 'sarif'))
    outputs = {**{key: path.as_posix() for key, path in paths.items()}, 'directory': directory.as_posix(), 'exit-code': str(report['exit_code'])}
    if any('\n' in value or '\r' in value for value in outputs.values()): raise ValueError('Invalid runner output path')
    if os.environ.get('GITHUB_OUTPUT'):
        with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as stream:
            stream.write(''.join(key + '=' + value + '\n' for key, value in outputs.items()))
    annotated = 0
    prefix = root.relative_to(Path(os.environ['GITHUB_WORKSPACE']).resolve()).as_posix()
    for finding in report.get('findings', []):
        if finding.get('existing') or annotated >= 50: continue
        severity = {'error': 'error', 'warning': 'warning', 'note': 'notice'}[finding['severity']]
        properties = []
        if finding.get('path'):
            path = (Path(prefix) / finding['path']).as_posix()
            if len(path) <= 1024:
                properties.append('file=' + escape(path, True))
                if finding.get('line'): properties.append('line=' + str(finding['line']))
        print('::' + severity + (' ' + ','.join(properties) if properties else '') + '::' + annotation(finding['message']))
        annotated += 1
    if report['status'] == 'error': print('::error::' + annotation(report['summary']))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        brief = {key: report[key] for key in ('version', 'tool', 'summary', 'status', 'exit_code')}
        brief['findings'] = report.get('findings', [])[:50]
        text = render(brief, 'markdown')
        # Summary limits do not truncate the complete JSON/SARIF artifacts.
        if len(text.encode()) > 128 * 1024:
            brief['findings'] = []
            brief['summary'] = 'Report exceeded the inline summary limit; inspect the complete artifacts.'
            text = render(brief, 'markdown')
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
            stream.write(text)
            stream.write(f'\nGate status: {report["exit_code"]}. {annotated} annotations emitted; complete evidence is in the report artifacts.\n')
    return report['exit_code']


def run(options):
    from devpocket.configuration import inspect
    from devpocket.engine import clean, failure
    from devpocket.checks import pipeline
    from devpocket.project import load
    from devpocket.workspace import check
    from devpocket import __version__
    root = options['root']
    directory = Path(tempfile.mkdtemp(prefix='devpocket-report-', dir=os.environ['RUNNER_TEMP'])).resolve()
    try:
        config = options['config'].relative_to(root).as_posix()
        preflight = inspect(root, config, options['mode'] == 'workspace')
        if not preflight.data['configuration_valid']:
            report = {'schema': 1, 'version': __version__, 'tool': 'config-validate', 'status': 'failed', 'exit_code': 1, 'summary': preflight.summary, 'findings': [f.as_dict() for f in preflight.findings], 'data': preflight.data}
        else:
            kwargs = {key: options[key] for key in ('jobs', 'allow_exec', 'fail_on', 'baseline')}
            report = check(root, config, **kwargs) if options['mode'] == 'workspace' else pipeline(load(root, options['config']), root, **kwargs)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report = failure('check', str(exc))
    return publish(clean(report), root, directory)


def main():
    try:
        options = inputs()
        if sys.argv[1:] == ['--run']:
            return run(options)
        if sys.argv[1:]: raise ValueError('Unsupported action invocation')
        environment = Path(tempfile.mkdtemp(prefix='devpocket-env-', dir=os.environ['RUNNER_TEMP']))
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        source = Path(os.environ['GITHUB_ACTION_PATH']).resolve()
        subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', str(source)], check=True, timeout=180)
        if options['requirements']:
            version = subprocess.check_output([str(python), '-c', 'from devpocket import __version__; print(__version__)'], text=True).strip()
            if not re.fullmatch(r'\d+\.\d+\.\d+', version): raise ValueError('Installed action version is invalid')
            constraint = environment / 'host-constraint.txt'
            constraint.write_text('devpocket-toolkit==' + version + '\n', encoding='utf-8')
            subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '--constraint', str(constraint), '-r', str(options['requirements'])], cwd=os.environ['GITHUB_WORKSPACE'], check=True, timeout=180)
        return subprocess.run([str(python), str(Path(__file__).resolve()), '--run'], timeout=7200).returncode
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('DevPocket action: ' + escape(str(exc)), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
