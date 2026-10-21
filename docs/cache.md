# Reuse deterministic checks

[Back to DevPocket](../README.md) · [Project checks](project-checks.md) · [Plugin SDK](plugins.md)

DevPocket 0.4 can reuse a diagnostic result when its declared inputs are unchanged. Caching requires two explicit choices: the tool author opts into a deterministic read-only contract, and the project config declares the files and environment values that affect that check. Ordinary checks, direct `run` commands and MCP calls remain uncached.

```json
{
  "version": 1,
  "checks": {
    "logs": {
      "tool": "loglens",
      "input": {"paths": ["logs/build.log"]},
      "cache": {
        "inputs": ["logs/build.log"],
        "env": [],
        "max_age": 3600
      }
    }
  }
}
```

Run `devpocket check --format json` twice. Each check's report records `cache.status` as `miss`, `hit` or `bypass`, together with the key and bounded hashing counts, or the reason reuse was unavailable. A hit preserves the original diagnostic's `seconds`; the parent check report measures the current pipeline's wall time. Hashing and worker startup still take time, so a small check may see no speed benefit.

## Inputs and invalidation

`inputs` needs 1–32 explicit root-relative POSIX file or directory names. Directories are recursive; globs, traversal, absolute paths and symlinks are refused. Missing paths, empty directories, additions, deletions and file/directory transitions affect the key. `.git`, Python bytecode caches and the result-cache directory are excluded from recursive traversal. Declare source/config data explicitly rather than selecting an entire virtual environment.

The key includes content hashes, selected environment-value hashes, input parameters, schema/contract version, project root, interpreter/platform, installed distribution names/versions, host source and the runner's Python package files. Timestamps alone cannot produce a hit. Inputs are checked again before a newly computed result is saved, and a hit is checked against a second input snapshot.

**Declare every result-affecting input.** Include configuration files, data dependencies and relevant environment variable names. Unlisted files, external services, time, randomness and editable dependencies outside the runner package cannot be inferred. Do not cache diagnostics that depend on those unless the complete dependency can be represented and the tool's contract supports it. Version fingerprints do not detect every same-version edit in another installed dependency. Bump the plugin's cache contract or clear the cache when making such changes.

`max_age` defaults to 3,600 seconds and accepts 1–604,800. `env` accepts at most 32 variable names; absence differs from an empty value. Input contents and environment values are hashed, not copied into cache metadata. Diagnostic reports are stored after normal redaction and can still contain private project information.

## Gates and failures

Only successful diagnostic execution (`status=completed`, `exit_code=0`) is stored. Warning/error findings from that execution can be cached, and still fail the configured severity gate. Baselines are applied afresh to each result. Dependency scheduling runs as usual: cached success cannot bypass a failed prerequisite. Tool errors, command failures, excessive inputs, permission errors, changing inputs and unsafe paths never become cached success.

`--allow-exec` bypasses result caching. A read-only declaration is a plugin author's promise, not a filesystem or network sandbox. Plugin discovery still does not import disabled tools; enabled plugin factories load in a worker even on hits. Caching does not make hostile Python code safe.

## Inspect, bypass or clear

```bash
devpocket cache status --json
devpocket check --no-cache
devpocket cache clear
```

The project-local `.devpocket/cache-v1` directory uses private entry permissions where supported, atomic replacements and an integrity digest. Corrupt/expired entries cause real execution. This is a trusted local cache, not a signed remote cache or a defence against someone who can rewrite local files. Clearing only removes recognized regular entry files; unrelated files and symlink targets are retained.

Hashing is bounded to 10,000 entries and 64 MiB per snapshot. Storage retains at most 256 entries and 64 MiB, evicting older entries. A limit bypasses caching rather than hiding the diagnostic.

## Plugin authors

The built-in `testlens` tool supports caching when every XML input is declared in `cache.inputs`. Failed tests, failed count gates and malformed reports are never cached as successes. EnvGuard remains uncached so its sensitive dotenv inputs are not added to this workflow by default. See [CI diagnostics](ci-tools.md).

Set `ToolSpec(..., cache_version="your-check-v1")` only for deterministic read-only tools whose dependencies users can completely declare. Change the contract version when interpretation changes. The field is optional; older API v1 plugins remain valid and are uncached by default. Using this new field requires DevPocket 0.4 or later. The scaffold now generates a compatible example and host dependency.
