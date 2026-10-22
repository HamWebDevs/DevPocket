# Environment setup and saved test evidence

[Back to DevPocket](../README.md) · [Project checks](project-checks.md) · [Plugin SDK](plugins.md)

EnvGuard and TestLens are built-in read-only tools in DevPocket 1.2. They require no plugin installation or runtime dependencies. Use their standalone commands, `devpocket TOOL`, structured `devpocket run TOOL`, project/workspace checks or MCP.

## EnvGuard

```bash
envguard --root . --example .env.example --env .env
envguard --ignore OPTIONAL_DEBUG --allow-extra --json
```

The template declares the required names. Every non-ignored template name must exist with a nonempty assignment in the target. Missing/empty names are errors, duplicate assignments and undocumented target names are warnings. `--allow-extra` suppresses undocumented-name findings; repeat `--ignore NAME` for optional names. Ignore policies do not suppress malformed syntax. An empty reference produces an error.

Only variable names, locations, counts and fixed diagnostic messages are returned. Values, comments and malformed source snippets are withheld, including in JSON, SARIF and MCP. The process environment is neither read nor modified. Input filenames and variable names can themselves be private.

Supported syntax is deliberately narrow: ASCII `NAME=value` identifiers (up to 128 characters), optional `export`, whitespace, comments and single/double-quoted multiline values with backslash escapes. `${NAME}`, command substitutions and escape sequences are not evaluated. A missing value, comment-only value, `''` or `""` is empty; quoted whitespace is not. Duplicate names use the last assignment for the emptiness check. Assignment-looking lines inside a quoted value remain value text. It does not validate whether a value is a usable URL, credential or application setting, or interpret every dotenv dialect. Missing files/invalid UTF-8/unsafe paths are execution errors.

Dotenv reads are bounded to 512 KiB, 20,000 lines and 1,024 unique names/findings per file. EnvGuard remains uncached. Stop concurrent writers before inspection; observed input changes are refused.

## TestLens

```bash
testlens reports/unit.xml reports/integration.xml --min-tests 10 --max-skipped 0
testlens reports/unit.xml --max-test-seconds 5 --json
```

Generate JUnit XML using your existing test runner first. TestLens reads the saved files; it never runs or imports test code. `testsuite`/`testsuites` roots, nested suites and XML namespaces are supported. Actual `testcase` records determine totals. Direct `failure`, `error` and `skipped` children determine outcomes. Suite counter attributes, when present, must match the descendant records; summary-only/truncated/inconsistent evidence is refused.

The default minimum is one recorded testcase. `--min-tests 0` explicitly permits empty reports. Skips are counted but permitted unless `--max-skipped` sets a limit. Any failure/error record or failed count gate returns a nonzero tool exit status even with `--fail-on none` or a finding baseline. Malformed or incomplete XML is an execution error and cannot be baselined into a pass.

Repeated classname/name identities are counted as separate records. A mixture of outcomes is flagged with a warning; retries, separate runs and duplicate names can explain it. This is evidence of mixed records, not proof of flakiness or regression. Failure text, messages, stdout, stderr, source paths, properties and suite-level timing attributes are discarded. Testcase `time` attributes are retained as seconds; missing times remain unknown. Findings expose bounded, redacted test names plus a stable identity suffix and the input XML path. Naming tests with credentials is still inappropriate; redaction is best effort.

### Recorded timing evidence

`data.timing` includes timed/missing record counts, the known sum and maximum, and up to ten slowest records with bounded redacted names, outcomes and input XML paths. Every recorded testcase affects totals and the optional duration gate, including records omitted from the ranking. A sum can include parallel tests and retries; it is not elapsed wall time.

`--max-test-seconds N` (SDK input `max_test_seconds`) requires every testcase record, including skipped/repeated records, to have a time at or below N. Equality and recorded zero pass. A known overage fails even when another record has no time; otherwise missing times or an empty report produce an unknown gate. Both fail and unknown return nonzero independently of severity baselines. Without this option, missing times are descriptive and do not fail an otherwise passing run. Invalid/negative/nonfinite times are refused with the value withheld. Supported testcase times and budgets range from zero to 1e9 seconds.

This reports saved XML assertions, not independently measured performance. No tests are run. Timing checks are available through CLI, project/workspace checks, JSON/SARIF and MCP; cache identity includes the new timing input and parser version.

Inputs must be UTF-8 (BOM allowed); XML declarations may specify UTF-8 or ASCII. DTDs/entities and conflicting outcome markers are refused. Paths are explicit root-relative POSIX names, not globs. Duplicate normalized paths, symlinks, redirected directories and non-regular inputs are refused. Limits: 64 inputs, 4 MiB each/16 MiB combined, 100,000 XML elements per input, depth 64, 20,000 combined testcase records and the normal 2 MiB report budget. Excessive evidence fails rather than silently truncating into a passing result.

## Project and CI integration

```json
{
  "version": 1,
  "checks": {
    "environment": {
      "tool": "envguard",
      "input": {"example": ".env.example", "env": ".env"}
    },
    "test-results": {
      "tool": "testlens",
      "input": {"paths": ["reports/junit.xml"], "min_tests": 10, "max_skipped": 0}
    }
  }
}
```

Run `devpocket check --format sarif --output checks.sarif` after creating the dotenv target and generating test reports. The GitHub Action runs the same configured checks. Each project in a workspace keeps its own input root. The [passing example](../examples/ci-checks.json) uses demonstration data only; it does not contain credentials.

TestLens opts into the existing [cache contract](cache.md). Add `"cache": {"inputs": ["reports/junit.xml"], "env": []}` to the check only when every XML input is covered. Direct runs and MCP remain uncached. Read-only MCP exposes both tools by default under the selected root; returned dotenv values and JUnit bodies remain withheld.
