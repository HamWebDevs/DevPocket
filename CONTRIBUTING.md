# Contributing

Keep the toolkit small, understandable and usable without runtime dependencies.

1. Use Python 3.10-compatible code.
2. Add a temporary-directory integration test for new behaviour or a regression.
3. Run `python -m unittest discover -s tests -v`.
4. Update the relevant guide and CHANGELOG when flags, exclusions, exit codes or limits change.
5. Run `python -m devpocket reporadar --root .` and review findings.
6. Submit a focused pull request explaining the user problem and validation.

Do not add telemetry, automatic uploads, automatic execution of repository instructions, or silent destructive behaviour. UndoRun changes need conflict, traversal and damaged-backup tests. Redaction changes need positive and negative examples without real credentials.

Suggestions, bug reports and small fixes are welcome. Include the operating system, Python version, command shape and a minimal reproducer. Review reports and remove secrets before posting them.

## Package layout

Each tool lives in `devpocket/TOOL.py`, with CLI flags and standalone aliases in `devpocket/cli.py`. Packaging entry points are in `pyproject.toml`; tests live in `tests/`; detailed guides and the repository banner live in `docs/`. Keep Python 3.10 compatibility and avoid runtime dependencies.

## Extending without changing the core

Prefer a plugin when your tool is domain-specific or needs external dependencies. Start with `devpocket plugins scaffold ./my-check --name my-check` and read [the SDK guide](docs/plugins.md). No core fork is required. Proposals for core additions should explain why the tool belongs in the dependency-free host.

Platform changes should cover process boundaries, timeout/cancellation, disabled plugin behaviour, schema errors and report compatibility. Run `python examples/verify_extension.py` for packaging/integration coverage. Keep public API/report/config versions explicit and document compatibility changes.
