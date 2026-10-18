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
