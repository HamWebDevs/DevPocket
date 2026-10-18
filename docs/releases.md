# Publish a GitHub release

[Back to DevPocket](../README.md)

The **Release** GitHub Actions workflow runs the full unittest suite, verifies a real installed extension, builds a Python wheel and source distribution, checks package metadata and generates `SHA256SUMS`. It publishes those files with notes from the matching changelog section. GitHub provides tagged source archives too. Nothing is uploaded to PyPI.

For a new version:

1. Update `pyproject.toml`, `devpocket/__init__.py` and `CHANGELOG.md` together, then merge the tested change into `main`.
2. Open **Actions → Release → Run workflow** on `main`, or push a `vX.Y.Z` tag matching the package version.
3. Inspect the workflow result and the published release assets.

The workflow also runs when its release automation files change on `main`, bootstrapping the first release. It uses the repository's automatic job token with `contents: write`; no personal access token is required. Existing published versions are skipped. Existing drafts need review, and an existing tag pointing to another commit is never moved. Use a new version for changed package contents.

Only final `X.Y.Z` versions are handled by this workflow. Validate uploaded packages with `sha256sum -c SHA256SUMS` after downloading both package files and the checksum file into the same directory. A checksum checks bytes; it is not a code-signing identity.
