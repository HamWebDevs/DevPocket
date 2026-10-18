"""Generate a complete installable example plugin, without executing it."""
from pathlib import Path
from .common import write_text
from .sdk import NAME


def scaffold(destination, name):
    if not NAME.fullmatch(name):
        raise ValueError("Plugin names must be lowercase letters, digits and hyphens (max 64 characters)")
    from .builtin_tools import specs
    if name in specs():
        raise ValueError("Plugin name conflicts with a built-in tool")
    root = Path(destination).resolve()
    if root.exists():
        raise ValueError("Scaffold destination must not already exist")
    module = "devpocket_plugin_" + name.replace("-", "_")
    root.mkdir(parents=True)
    content = {
        "pyproject.toml": f'''[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "devpocket-tool-{name}"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["devpocket-toolkit>=0.3,<0.4"]

[project.entry-points."devpocket.tools"]
{name} = "{module}:build_tool"

[tool.setuptools.packages.find]
include = ["{module}*"]
''',
        module + "/__init__.py": f'''"""Example DevPocket API v1 plugin: find long lines in a selected text file."""
from devpocket.sdk import Finding, ToolResult, ToolSpec


def inspect(context, params):
    path = context.resolve(params["path"])
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Example plugin accepts files up to 1 MiB")
    maximum = params.get("max_length", 100)
    findings = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if len(line) > maximum:
            findings.append(Finding("long-line", f"Line has {{len(line)}} characters (limit {{maximum}})", path=path.relative_to(context.root).as_posix(), line=number))
    return ToolResult(f"{{len(findings)}} long lines", findings)


def build_tool():
    return ToolSpec(
        name="{name}",
        description="Example plugin: find long lines in a selected text file",
        input_schema={{"type": "object", "properties": {{"path": {{"type": "string", "maxLength": 4096}}, "max_length": {{"type": "integer", "minimum": 1, "maximum": 100000}}}}, "required": ["path"], "additionalProperties": False}},
        run=inspect,
    )
''',
        "test_plugin.py": f'''import tempfile
from pathlib import Path
import unittest
from devpocket.sdk import ToolContext
from {module} import build_tool

class PluginTests(unittest.TestCase):
    def test_detects_long_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "sample.txt").write_text("abcdefghij\\n", encoding="utf-8")
            result = build_tool().run(ToolContext(root), {{"path": "sample.txt", "max_length": 5}})
            self.assertEqual(len(result.findings), 1)

if __name__ == "__main__":
    unittest.main()
''',
        "README.md": f'''# {name}

A complete DevPocket API v1 plugin example. Change the schema, runner and tests to build your own check.

Install DevPocket 0.3 first, then install this plugin in the same Python environment:

```bash
python -m pip install .
python -m unittest discover -v
```

In the project you want to check:

```bash
devpocket plugins enable {name}
devpocket run {name} --input '{{"path":"README.md","max_length":100}}'
```

Enabling a plugin explicitly trusts its installed Python code for this project. A read_only declaration is a promise, not a sandbox. No plugin is downloaded or enabled automatically.
''',
        ".gitignore": "__pycache__/\n*.egg-info/\nbuild/\ndist/\n.venv/\n",
    }
    for filename, text in content.items():
        write_text(root / filename, text)
    return root
