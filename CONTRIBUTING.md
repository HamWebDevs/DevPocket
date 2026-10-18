# Contributing

Keep the toolkit small, understandable and usable without runtime dependencies.

1. Use Python 3.10-compatible code.
2. Add a temporary-directory integration test for new behaviour or a regression.
3. Run `python -m unittest discover -s tests -v`.
4. Update the README when flags, exclusions, exit codes or limits change.
5. Submit a focused pull request explaining the user problem and validation.

Do not add telemetry, automatic uploads, automatic execution of repository instructions, or silent destructive behaviour. UndoRun changes need conflict, traversal and damaged-backup tests. Redaction changes need positive and negative examples without real credentials.

Suggestions, bug reports and small fixes are welcome. Include the operating system, Python version, command shape and a minimal reproducer. Review reports and remove secrets before posting them.
