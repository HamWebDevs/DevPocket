"""Offline configuration preflight. Plugin discovery never imports plugin code."""
import json
from pathlib import Path

from . import __version__
from .common import write_text
from .engine import clean, gated_exit
from .project import validate
from .registry import Registry
from .reports import render
from .sdk import Finding, ToolResult, validate_input
from .workspace import compile_plan, contained, read_json


def inspect(root, config=None, workspace=False):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('Configuration root must be an existing directory')
    if workspace:
        plan, _, roots, configs = compile_plan(root, config or '.devpocket-workspace.json')
        manifest = read_json(contained(root, config or '.devpocket-workspace.json'))
        paths = {name: (roots[name] / manifest['projects'][name].get('config', '.devpocket.json')).relative_to(root).as_posix() for name in roots}
    else:
        filename = config or '.devpocket.json'
        configs = {'project': validate(read_json(contained(root, filename)))}
        paths, plan = {'project': filename}, None
    findings, count, unverified = [], 0, 0
    for name, definition in configs.items():
        registry = Registry(definition.get('plugins', []))
        path = paths[name]
        if not definition.get('checks'):
            findings.append(Finding('config-empty', 'No checks are configured', severity='error', path=path))
        for plugin in definition.get('plugins', []):
            if plugin in registry.builtins or len(registry.entries.get(plugin, [])) != 1:
                findings.append(Finding('config-plugin-unavailable', f'{plugin}: enable exactly one installed nonconflicting plugin', severity='error', path=path))
        for check, step in definition.get('checks', {}).items():
            count += 1
            tool = step['tool']
            if tool in registry.builtins:
                try:
                    validate_input(step.get('input', {}), registry.builtins[tool].input_schema)
                except ValueError:
                    findings.append(Finding('config-input-invalid', f'{name}/{check}: input does not match the {tool} schema; use tools describe to inspect it', severity='error', path=path))
            elif tool not in definition.get('plugins', []) or len(registry.entries.get(tool, [])) != 1:
                findings.append(Finding('config-tool-unavailable', f'{name}/{check}: {tool} must be installed once and enabled in this project', severity='error', path=path))
            else:
                unverified += 1
                findings.append(Finding('config-plugin-input-unverified', f'{name}/{check}: plugin input validation is deferred to the isolated worker; no plugin code was imported', severity='note', path=path))
    data = {'mode': 'workspace' if workspace else 'project', 'projects': len(configs), 'checks': count, 'plugin_inputs_unverified': unverified, 'configuration_valid': not any(f.severity == 'error' for f in findings), 'checks_executed': False}
    if plan:
        data.update(plan_sha256=plan['plan_sha256'], scope=plan['scope'])
    return ToolResult(f'{count} configured checks across {len(configs)} project(s); {unverified} plugin input schema(s) deferred', findings, data)


def adapter(ctx, params):
    return inspect(ctx.root, params.get('config'), params.get('workspace', False))


def execute(args):
    if args.output and (Path(args.output).exists() or Path(args.output).is_symlink()):
        raise ValueError('Output already exists; choose a fresh filename')
    if args.action == 'schema':
        text = Path(__file__).with_name('schemas').joinpath(args.kind + '-v1.json').read_text(encoding='utf-8')
        code = 0
    else:
        result = inspect(args.root, args.config, args.workspace)
        report = clean({'schema': 1, 'version': __version__, 'tool': 'config-validate', 'status': 'completed', 'exit_code': result.exit_code, 'summary': result.summary, 'findings': [f.as_dict() for f in result.findings], 'data': result.data})
        code = gated_exit(report)
        text = render(report, args.format)
    if args.output:
        write_text(Path(args.output), text)
    else:
        print(text, end='')
    return code


def register(tools):
    command = tools.add_parser('config', help='Validate configuration without executing checks or emit editor schemas')
    actions = command.add_subparsers(dest='action', required=True)
    validate_command = actions.add_parser('validate')
    validate_command.add_argument('--root', default='.')
    validate_command.add_argument('--config', help='Root-contained config path; defaults depend on --workspace')
    validate_command.add_argument('--workspace', action='store_true')
    validate_command.add_argument('--format', choices=('text', 'json', 'sarif', 'markdown'), default='text')
    schema = actions.add_parser('schema')
    schema.add_argument('--kind', choices=('project', 'workspace'), default='project')
    for child in (validate_command, schema):
        child.add_argument('--output')
        child.set_defaults(handler=execute)
