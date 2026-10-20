# CLI reference

[Back to DevPocket](../README.md) · [LogLens](loglens.md) · [ImportDoctor](importdoctor.md)

Commands below run from the project checkout or after installation. All runtime dependencies are part of Python itself.

## Oopsfile — useful error reports, in one command

```bash
oopsfile run -- python app.py
```

On failure, creates `oops-report.md` with the command, exit code, timeout status, bounded stdout/stderr and a snapshot of the reporting Python interpreter's environment. On success it creates no report. The wrapped command's exit status is preserved; timeout is 124.

Opt in to local source context and Git change statistics:

```bash
oopsfile run --include-source --include-diff --output bug.md -- python app.py
```

Source capture reads at most five project-local Python traceback files, up to three lines either side of the frame. Git capture includes unstaged diff statistics, not patch contents or staged changes. Environment details describe the interpreter running DevPocket; if the wrapped command uses another interpreter, capture that environment separately with EnvTwin.

Output can contain source or sensitive information even without `--include-source`. Known token patterns, credential assignments, bearer tokens, credentialed HTTP URLs and private key blocks are redacted on a best-effort basis. **Review every report before sharing it.** No report is uploaded automatically.

## EnvTwin — compare what actually differs

On machine A, in the environment you want to inspect:

```bash
envtwin snapshot --output machine-a.json
```

On machine B:

```bash
envtwin snapshot --output machine-b.json
```

Bring the two JSON files together:

```bash
envtwin diff machine-a.json machine-b.json
envtwin diff machine-a.json machine-b.json --json
```

Compares Python version/implementation, virtual environment status, OS/release/architecture/libc, installed Python distribution versions, presence of common developer tools and presence of a small allowlist of environment variable names. It never collects environment variable values, hostname, username, executable paths or full configuration files. Package names and versions can still be private information.

It reports differences, not guaranteed causes. Tool versions and arbitrary system-library inventories are not captured. Use the same DevPocket version on both machines.

## UndoRun — inspect and reverse scoped file changes

```bash
undorun run --root ./scratch-project -- python generate.py
```

Makes a local backup **before** executing the command, prints the changed files and gives you a run ID. Preview restoration first, then apply it:

```bash
undorun restore RUN_ID --root ./scratch-project
undorun restore RUN_ID --root ./scratch-project --apply
```

Replace `RUN_ID` with the printed ID. Restoration removes captured newly created files and restores captured modified/deleted regular files and their permission bits. It refuses the entire restore during preflight if an affected file has changed again, a target traverses a symlink, or a backup is damaged.

Backups live in `.devpocket/runs/` beneath the selected root. Keep them private. They are intentionally ignored by Git. Run against a small project copy and stop other writers during capture and restoration.

- This is a scoped backup utility, **not a sandbox or a way to trust unknown code**. The command retains all normal permissions and network access.
- Changes outside `--root` cannot be restored. Files in excluded directories, secret-like files, symlinks, databases and special files are not captured. Renames appear as deletion/creation.
- Excludes include `.git`, `.venv`, `venv`, `node_modules`, caches, `dist`, `build` and `.devpocket`. Secret-like exclusions include `.env*` (except example templates), private keys, credential/secret filenames and `*.db`/`*.sqlite*` files. These are heuristics, not exhaustive classifications.
- Add exclusions with repeatable relative globs, e.g. `--exclude 'uploads/*'`. Directory patterns are matched against the relative directory path, too.
- Backup limits: 5,000 files, 64 MiB total, 8 MiB per file; checked before the command runs. Inventory limit: 20,000 files. If post-run inventory fails, backups remain but automatic restoration is unavailable without a completed after-journal.
- Empty directories, ownership, ACLs, extended attributes and timestamps are not restored. Restoration is atomic per file, not a transaction across all files; an OS error during application can leave a partial restore. No concurrent-run locking.
- Interrupted runs retain the before-backup but may have no after-journal. On POSIX timeouts kill the command's process group; on Windows only the immediate child is killed. Do not leave background writers running.

## FlakeTrail — make intermittent failure visible

```bash
flaketrail --runs 20 --timeout 30 -- python -m unittest tests.test_sometimes
```

Runs the command sequentially, prints each outcome and saves `flake-report.json`. Includes exit status, duration, timeout/truncation flags, bounded output for each run, pass/fail median duration and a unified diff between the first passing and first failing output.

```bash
flaketrail --runs 5 --output flakes.json -- python flaky_script.py
```

It reruns the command with its normal side effects. Use repeatable tests or a disposable fixture. There is no automatic state reset, random seed injection, test-order randomisation, resource tracing or root-cause claim. Identical output with different exit codes can legitimately produce an empty output diff.

## RepoRadar — the small checks people forget

```bash
reporadar --root .
reporadar --root . --json
```

Read-only, offline heuristics for:

- Missing root README or licence.
- Python projects without obvious test files.
- Broken relative Markdown file links outside fenced code blocks.
- Literal `node file.js` / `python file.py` references to missing files in `package.json` scripts.
- Literal required `os.environ['NAME']` accesses absent from root `.env.example`, `.env.sample` or `.env.template`.
- Malformed `package.json` files encountered by the scan.

Findings include relative paths and line numbers where available. It does not run setup instructions, package scripts or network checks, validate every dependency constraint, parse every Markdown dialect, or prove a project is correct. Treat findings as review prompts.

## EnvGuard and TestLens

```bash
envguard --example .env.example --env .env --ignore OPTIONAL_NAME
testlens reports/unit.xml reports/integration.xml --min-tests 10 --max-skipped 0
```

Both commands accept `--root` and `--json`; filenames are relative to the selected root. EnvGuard compares names without returning values. TestLens reads already-written JUnit XML and never executes tests. Full schemas, examples, privacy and limits are in the [CI diagnostics guide](ci-tools.md).

## CLI conventions

Put options **before** the wrapped command and use `--` to separate it. Commands run as argument lists, without a shell, with stdin disconnected. Pipes, redirects and shell built-ins require an explicit shell that you choose, e.g. `-- sh -c '...'` on POSIX. Shell behaviour is then your responsibility.

Each stream retains its last 128 KiB. Oopsfile/FlakeTrail redact output before printing or saving; UndoRun prints raw output as a normal command runner. Reports are UTF-8, created with restrictive permissions where supported, and **never overwrite an existing report**: choose a fresh `--output` or move the previous file. Output paths are relative to the terminal's original working directory, even when `--root` is supplied.

| Command | Exit status |
| --- | --- |
| Oopsfile / UndoRun run | Wrapped command status; timeout 124 |
| EnvTwin diff | 0 same captured fields; 1 different |
| FlakeTrail | 0 all runs passed; 1 one or more failures |
| RepoRadar | 0 no findings; 1 findings |
| Usage / tool error | 2 |
| Interrupted | 130 |

## Try the examples

From this checkout:

```bash
python -m devpocket oopsfile run --include-source -- python examples/crash.py
python -m devpocket flaketrail --runs 4 -- python examples/flaky.py
```

The crash deliberately fails. The flaky example alternates success/failure using a counter in your system temporary directory. Both commands deliberately return nonzero.


The two newer tools have dedicated guides: [LogLens](loglens.md) and [ImportDoctor](importdoctor.md).
