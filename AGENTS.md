# Working on DevPocket

DevPocket is a Python 3.10+ CLI package with no runtime dependencies.

- Run from the repository root. Install for development with `python -m pip install -e .`.
- Verify functional changes with `python -m unittest discover -s tests -v`.
- Verify documentation links and basic repository health with `python -m devpocket reporadar --root .`.
- Keep public commands in `devpocket/cli.py`; each tool implements `execute(args)` and returns an integer exit status.
- Add standalone entry points in both `cli.py` and `pyproject.toml` for new commands.
- Test with temporary directories or streams; never modify the real checkout from a test.
- Keep all target execution explicit. ImportDoctor must not execute target modules, RepoRadar must not execute setup instructions, and LogLens must not execute log content.
- Preserve report redaction, bounded capture, output-file collision protection and UndoRun's restore preflight.
- Update the relevant guide and CHANGELOG for user-visible changes. Keep version values in `pyproject.toml` and `devpocket/__init__.py` aligned.
- Do not add telemetry, automatic uploads, required external services or runtime dependencies without an explicit request.
- Keep code and fixtures free of real credentials or private logs.
- AssetGuard inspects only finished artifacts. Preserve private-file metadata-only handling, mutation/symlink refusal and honest gzip/coverage limits; never fetch resource URLs or execute target HTML/JavaScript.

## Extension platform (0.3+)

- The public extension contract is `devpocket/sdk.py` API v1. Validate schemas before executing plugin runners.
- Discover plugins through entry-point metadata only. Do not import disabled plugins or let plugins shadow built-ins.
- CLI/check invocations use `checks.invoke` workers. Preserve bounds, timeout/cancellation cleanup, structured JSON envelopes and secret redaction.
- MCP must retain clean protocol-only stdout, explicit initialization, read-only defaults and explicit plugin exposure. Never add shell execution to its default tools.
- Fingerprints and baselines must not suppress tool execution failures.
- Verify extension changes with `python examples/verify_extension.py`; it builds real wheels and installs into a temporary environment. This may install build dependencies from the configured registry. With setuptools/wheel already available, use `--no-build-isolation`.
- The `examples/plugins/long-lines` package is generated from the scaffold and should stay aligned with it.

## Result caching (0.4+)

- Caching is opt-in in both ToolSpec and project configuration. Preserve complete input declarations, source/runtime fingerprints, bounded hashing/storage and symlink refusal.
- Baselines and gates apply to fresh decoded raw reports, including cache hits. Never cache execution failures or allow cached results to bypass failed dependencies.
- Recheck inputs before storing/reusing a result; cache errors must fall back to real execution. Keep direct runs and MCP calls uncached.

## Workspaces (0.6+)

- Planning must not execute checks or import plugins. Keep input values out of public plans and identify selected/unselected scope in reports.
- Use one globally bounded worker pool with each project's own root/plugins/cache configuration. Expand affected dependents and prerequisites; unmapped/shared/config changes select all.
- Relocate copies of findings and namespace fingerprints by project before baseline/dependency gates. Never rewrite raw cached reports.
- Keep strict path/config/aggregate-report bounds and cleanup on interruption or resource exhaustion. A plan digest binds configuration/selection, not filesystem contents or plugin identity.
