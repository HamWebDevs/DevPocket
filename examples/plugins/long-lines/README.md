# long-lines

A complete DevPocket API v1 plugin example. Change the schema, runner and tests to build your own check.

Install DevPocket 0.4, 0.5 or 0.6 first, then install this plugin in the same Python environment:

```bash
python -m pip install .
python -m unittest discover -v
```

In the project you want to check:

```bash
devpocket plugins enable long-lines
devpocket run long-lines --input '{"path":"README.md","max_length":100}'
```

Enabling a plugin explicitly trusts its installed Python code for this project. A read_only declaration is a promise, not a sandbox. No plugin is downloaded or enabled automatically.

This example opts into deterministic result caching with `cache_version="long-lines-v1"`. To cache it in project checks, declare the selected file in `cache.inputs`. Keep the contract version current when changing diagnostic semantics. Caching is off unless the check config requests it.
