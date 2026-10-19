# AssetGuard: review the build you will deploy

[Back to DevPocket](../README.md) · [Project checks](project-checks.md) · [Network evidence with ReclaimLab](https://github.com/HamWebDevs/ReclaimLab/blob/main/docs/browser-network.md)

AssetGuard inspects a finished build directory from any toolchain. It measures raw bytes and reproducible gzip level 9 estimates, checks explicit HTML and literal CSS resource references, identifies identical files and records a content-hash snapshot. It never runs a build, executes JavaScript or fetches URLs.

## Start with a finished build

```bash
assetguard --root dist
assetguard --root dist --json
assetguard --root dist --public-path /my-project/
```

`--public-path` describes the deployment URL prefix, not a filesystem directory. Root-relative URLs must stay inside that prefix. Relative URLs resolve against the HTML document and its first `<base href>`; queries and fragments do not affect local-file lookup. External URLs and non-HTTP schemes are counted but never fetched.

The built-in sample can be inspected immediately from this checkout:

```bash
assetguard --root examples/web-dist --max-total-gzip-kib 16
devpocket check --config examples/web-checks.json --format json
```

## Compare builds without guessing chunk identities

```bash
assetguard --root dist --snapshot artifacts/build-before.json
# Make your change and finish your normal build.
assetguard --root dist --baseline artifacts/build-before.json --max-growth-kib 32
```

Snapshots must be saved outside the inspected build directory and never overwrite an existing file. They contain relative filenames, byte counts and SHA-256 content hashes, without file bodies or absolute checkout paths. Review filenames before sharing. Keep baselines trusted and review baseline replacements in code review.

The comparison reports added, removed and changed paths; gzip deltas by asset kind; unique new-content gzip bytes; and byte-identical files that were renamed. Hashed chunk names are compared through actual contents. No heuristic claims that two different chunks are the same logical module. Identical renames do **not** establish HTTP cache reuse: URLs and server policy still matter.

Snapshots record the zlib runtime version. Different compressors can produce different sizes for identical input; a version mismatch makes regression comparison unavailable and cannot pass a requested growth gate. Generate before/after snapshots with the same compression runtime. Current-build total and individual-asset budgets can still be evaluated independently.

## Choose explicit budgets

| Option | Unit | Meaning |
| --- | --- | --- |
| `--max-total-gzip-kib` | KiB, 1,024 bytes | Maximum sum of gzip estimates across all measured output files. |
| `--max-asset-gzip-kib` | KiB | Maximum individual file gzip estimate. |
| `--max-growth-kib` | KiB | Maximum total gzip growth against `--baseline`. Negative growth is allowed. |

No size thresholds apply by default. These are project budgets; choose them for your users and deployment. Values must be finite and nonnegative. A budget is exceeded only when the measured value is greater than the limit.

Gzip estimates cover all output files, including maps, images and every route's assets. They are **not** initial-route transfer sizes, Brotli estimates, server compression guarantees or browser performance measurements. Use a captured HAR with ReclaimLab to inspect actual recorded HTTP response sizes and waits.

## CI, SARIF and MCP

Add a check to your project's `.devpocket.json`:

```json
{
  "version": 1,
  "checks": {
    "production-assets": {
      "tool": "assetguard",
      "input": {
        "path": "dist",
        "public_path": "/",
        "baseline": "artifacts/build-before.json",
        "max_total_gzip_kib": 1024,
        "max_asset_gzip_kib": 256,
        "max_growth_kib": 32
      }
    }
  }
}
```

Omit `baseline` and `max_growth_kib` when starting without a prior build. Build the application with your existing CI step before running checks:

```bash
devpocket check --format sarif --output assets.sarif
devpocket run assetguard --input '{"path":"dist","max_total_gzip_kib":1024}' --format json
```

Findings carry project-relative locations. Baselines, dependency gates and severity policies work as usual. The read-only adapter is also available through the default MCP tool list. It returns the inventory in memory and cannot write snapshots. AssetGuard always rescans the build; it does not opt into result caching because deployment metadata is also part of its inspection.

## Findings and boundaries

| Finding | Severity | Interpretation |
| --- | --- | --- |
| `missing-build-resource` | Error | An explicit HTML or literal CSS resource is absent from the output inventory. |
| `css-reference-coverage` | Warning | A stylesheet has malformed/unsupported URL tokens or an unsupported encoding; resource coverage is incomplete. |
| `resource-outside-public-path` | Error | A local resource URL leaves the configured deployment prefix. |
| `invalid-resource-url` | Error | A local reference has an invalid URL/path. |
| `private-build-entry` | Error | A secret-like filename or version-control metadata appears in deployment output. Private file contents are not read. |
| `asset-budget-unknown` | Error | Unmeasured private entries prevent verification of a requested size budget. |
| `total-gzip-budget`, `asset-gzip-budget`, `gzip-growth-budget` | Error | An explicit project budget was exceeded. |
| `duplicate-build-content` | Note | Multiple files are byte-identical; separate copies may be intentional. |
| `published-source-map` | Note | A source map is present; review whether this deployment should publish it. |

The secret-like filename check is a useful deployment check, not a content-based secrets audit. HTML checks cover explicit resource `src`/`href` attributes, including scripts, styles, preloads and images. CSS checks inspect every non-private UTF-8 `.css` file for literal `url()` and string/URL `@import` references, including fonts and background images. Relative URLs resolve from each stylesheet's directory, independently of an HTML base element. CSS escapes, quoted strings, comments, fragments and embedded/remote URLs are handled without fetching anything. Missing local assets report the referring stylesheet and source line. Malformed tokens or unsupported encodings produce `css-reference-coverage` warnings and `css_unparsed_tokens`; this is not a full CSS validator.

Inline styles, `srcset`, string-only `image-set()` candidates, computed values, JavaScript imports, dynamic routes, rewrites and remote availability are outside coverage. CSS media/support conditions are not evaluated; a reference may belong to an unused branch. A generated server directory such as `.next` contains server artifacts too; point AssetGuard at the static output you actually publish. The scanner follows the literal URL/string and escape rules described in [CSS Syntax Level 3](https://www.w3.org/TR/css-syntax-3/).

Inspection refuses symlinks, non-regular files, unreadable traversal and observed filesystem changes. Limits: 3,000 files, 32 MiB per file, 256 MiB total, 20,000 combined HTML/CSS references and 1,000 findings. Use a finished, stable build; this is not an atomic filesystem snapshot or a sandbox against concurrent hostile writers. Builds with unmeasured private entries cannot produce a comparable size regression result.

Standalone exits: **0** inspection completed with no error findings; **1** deployment/budget errors; **2** invalid input or inspection failure; **130** interrupted. Notes do not fail a standalone run. Structured runs use DevPocket's chosen severity gate.
