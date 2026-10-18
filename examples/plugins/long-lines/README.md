# long-lines

A complete DevPocket API v1 plugin example. Change the schema, runner and tests to build your own check.

Install DevPocket 0.3 first, then install this plugin in the same Python environment:

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
