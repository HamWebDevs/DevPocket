# ImportDoctor

[Back to DevPocket](../README.md)

Diagnose Python import resolution without importing the module being investigated. Especially useful when a local `json.py`, `requests.py` or similarly named package hides the thing you intended to load.

## Usage

```bash
importdoctor requests
importdoctor yaml.loader --distribution PyYAML
importdoctor json --root ./project --json
```

Inspect the environment that actually runs your application:

```bash
/path/to/venv/bin/python -m devpocket importdoctor requests --root ./project
```

DevPocket must be installed in that interpreter or available from the current checkout. On Windows, use the corresponding Python executable path. `--expect-python` compares against a supplied executable path; it does not launch that interpreter:

```bash
importdoctor requests --expect-python /path/to/venv/bin/python
```

## What it checks

- The diagnostic interpreter's executable, version and virtual-environment status.
- Whether a dotted import name resolves through static finder specifications.
- Project-local files/packages taking precedence over standard-library names, installed distributions or alternative import candidates.
- Whether a parent is an ordinary module rather than a package.
- Namespace packages and their search locations.
- Installed distribution names and versions associated with the top-level import.
- An explicit `--distribution` name, useful when pip and import names differ.

The selected root replaces the diagnostic interpreter's first search-path entry. Other nonempty entries are retained, including site-packages. Built-in and frozen modules retain their normal precedence. No environment values are collected. Text and JSON outputs use the toolkit's best-effort redaction.

## Findings

| Code | Meaning |
| --- | --- |
| `resolved` | Static resolution succeeded without another finding. |
| `local-module` | The top-level module comes from the selected project; this may be intended. |
| `local-shadow` | A local module takes precedence over another likely candidate. |
| `module-not-found` | The import or a dotted child was not statically resolvable. |
| `namespace-package` | The top-level package has search locations but no single `__init__.py`. |
| `distribution-not-installed` | An explicitly named or mapped distribution is missing. |
| `interpreter-mismatch` | The current executable path differs from `--expect-python`. |

Exit code is 1 for a missing module/distribution, likely shadow or interpreter mismatch; 0 for an informational result without those problems; 2 for invalid input/tool errors; 130 for interruption. Local modules and namespace packages alone are not errors.

## Boundaries

This is static diagnosis, not a test import. Target modules and parent `__init__.py` files are not executed. Dynamic package `__path__` modifications, custom meta-path importers, runtime `sys.path` edits, editable-install finder hooks, modules already cached in a live process, transitive dependency errors and native-library loading can produce different runtime behaviour.

The tool uses the standard built-in, frozen and path finders. Existing interpreter startup hooks and path hooks are outside its control. Distribution mappings are metadata hints, not proof of which package owns an arbitrary local file. The tool does not install, uninstall, rename or edit anything, and does not claim to know the correct pip distribution for every missing import.
