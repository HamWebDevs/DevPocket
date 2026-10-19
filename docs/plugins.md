# Build and connect your own tools

[Back to DevPocket](../README.md) · [Project checks](project-checks.md) · [MCP](mcp.md)

DevPocket discovers installed plugins through the standard Python packaging entry-point group **`devpocket.tools`**. No registry account, fork of DevPocket or copy into its source directory is required. A plugin is an ordinary Python distribution installed in the same environment as the host.

## A working plugin in five commands

From a checkout or environment with DevPocket 0.4, 0.5 or 0.6 installed:

```bash
devpocket plugins scaffold ./my-check --name long-lines
python -m pip install ./my-check
devpocket plugins list
devpocket plugins enable long-lines
devpocket run long-lines --input '{"path":"README.md","max_length":100}'
```

The scaffold creates a complete package: packaging metadata, entry point, runner, input schema, README, test and ignore rules. It implements a useful example that finds long lines in a selected text file. Its warning findings deliberately return CLI gate status 1 when long lines exist. On shells with different quoting conventions, put the input in a file and use `--input @input.json`.

`plugins list` and `plugins enable` inspect metadata without importing plugin code. Enabling records the exact entry-point name in the selected project's `.devpocket.json`. Read the plugin before enabling it. Python package installation itself can execute build code; use normal care when installing packages.

The committed [reference plugin](../examples/plugins/long-lines/README.md) contains the same scaffold. The [extension verification script](../examples/verify_extension.py) builds real wheels, installs them in a new virtual environment and checks CLI, baselines, dependency checks, SARIF and MCP.

## The public API

```python
from devpocket.sdk import Finding, ToolResult, ToolSpec


def inspect(context, params):
    path = context.resolve(params["path"])
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Choose a file up to 1 MiB")
    lines = path.read_text(encoding="utf-8").splitlines()
    findings = [
        Finding(
            rule="todo-comment",
            message="TODO comment needs review",
            severity="note",
            path=path.relative_to(context.root).as_posix(),
            line=number,
        )
        for number, line in enumerate(lines, 1)
        if "TODO" in line
    ]
    return ToolResult("TODO review complete", findings, {"lines_scanned": len(lines)})


def build_tool():
    return ToolSpec(
        name="todo-review",
        description="Find TODO comments in one selected text file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "maxLength": 4096}},
            "required": ["path"],
            "additionalProperties": False,
        },
        run=inspect,
        read_only=True,
    )
```

Register that factory in `pyproject.toml`:

```toml
[project.entry-points."devpocket.tools"]
todo-review = "your_package:build_tool"
```

The factory is called with no arguments and must return a `ToolSpec` whose name matches the entry point. The supported SDK is **API v1** (`devpocket.sdk.API_VERSION == 1`), introduced in DevPocket 0.3. Unsupported API versions are rejected. Older API v1 plugins remain valid on 0.4, 0.5 and 0.6. Plugins should declare an appropriate host dependency; the scaffold uses `devpocket-toolkit>=0.4,<0.7` because it demonstrates the optional cache contract and is verified against the current host.

### Types and contracts

| Type | Contract |
| --- | --- |
| `ToolContext` | `root: Path`, `allow_exec: bool`; `resolve(relative)` refuses paths and symlinks escaping that root. This helper is not a sandbox. |
| `ToolSpec` | Name, description, input schema, `run(context, input)` callable, `read_only` declaration, `api_version` and optional `cache_version`. Names use lowercase letters, digits and hyphens, start with a letter and have at most 64 characters. |
| `ToolResult` | Summary string, a list of `Finding` objects, JSON-compatible data and optional nonzero `exit_code` for tool/command failure. Ordinary findings should leave `exit_code=0`; the host applies severity gates. |
| `Finding` | Stable rule ID, message, `note`/`warning`/`error` severity, optional relative POSIX path, positive line number and help text. Absolute paths and traversal are refused. |

Fingerprints include rule, severity, path and redacted message, deliberately excluding line numbers. Keep messages stable when you want baselines to survive code movement. Put changing counts or evidence in `data` or `help`. Moving a finding to a different file or changing its severity produces a different fingerprint.

`cache_version` defaults to `None`. In 0.4, deterministic read-only tools may set a 1–64 character contract version, such as `cache_version="my-check-v1"`. The project must also declare complete inputs before results are reused. Bump the contract when semantics change. Time-, service- or undeclared-environment-dependent tools should remain uncached. [Caching guide](cache.md).

### Input schema subset

API v1 accepts an explicit JSON Schema subset: `type`, `properties`, `required`, boolean `additionalProperties`, `items`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength`, `minItems`, `maxItems`, `description`, `title` and `default`. Supported types are object, array, string, integer, number, boolean and null. Every node needs a type. Unsupported keywords such as `$ref` or `oneOf` are rejected instead of silently ignored. Defaults are descriptive; apply missing defaults in your runner with `params.get(...)`.

Inputs are validated before the runner is called. Booleans are not accepted as integers. Plugin results must be JSON-compatible and at most 2 MiB before and after sanitisation, with at most 20,000 findings and at most 30 levels of nested data. Tool requests are capped at 1 MiB.

## Discovery, execution and trust

```bash
devpocket tools list --json
devpocket tools describe long-lines
devpocket plugins disable long-lines
```

Descriptions load enabled plugin factories to obtain their schema; discovery does not. Disabled plugins cannot be run. Duplicate installed entry points are rejected. Plugins cannot replace built-in commands. A built-in name collision is visible in the inventory and cannot be enabled as a plugin.

Structured runs execute in a separate worker process, with a configurable wall-clock timeout. Printed stdout/stderr is captured in bounded diagnostics rather than corrupting JSON results. Exceptions become explicit tool errors. Common credential patterns are redacted; this is best-effort, not a secret detector. A plugin writing directly to low-level stdout can break its worker response and will be reported as a tool error.

`read_only=True` is the plugin author's contract, not enforced filesystem or network isolation. Installed Python code has normal user privileges and can ignore `context.resolve`. Non-read-only tools need `--allow-exec` in structured CLI/check runs. The MCP server does not expose those tools. For an enabled read-only plugin to appear in MCP, the server owner must also pass `--plugin NAME` explicitly.

On POSIX the worker gets a termination grace period so built-in nested command runners can clean up their process groups. Windows timeout cleanup kills the immediate worker; descendant cleanup is limited. Hostile plugins, custom signal handlers and detached processes are outside these guarantees.

## Testing a plugin

Run its generated test with `python -m unittest discover -v` from the plugin directory. Add cases for real user inputs, invalid inputs, file boundaries, stable findings and failure behaviour. Test through the installed host as well as calling your runner directly. Plugins can have their own dependencies; DevPocket's core remains free of runtime dependencies.

Packaging references: [PyPA entry-point specification](https://packaging.python.org/en/latest/specifications/entry-points/) and [project metadata](https://packaging.python.org/en/latest/specifications/pyproject-toml/).
