"""Metadata-only discovery and explicit, version-checked plugin loading."""
from __future__ import annotations
import importlib.metadata as metadata

from . import builtin_tools
from .sdk import ToolSpec

GROUP = "devpocket.tools"


class Registry:
    def __init__(self, enabled=()):
        self.enabled = set(enabled)
        self.builtins = builtin_tools.specs()
        self.entries = {}
        self.cache = {}
        for entry in metadata.entry_points(group=GROUP):
            self.entries.setdefault(entry.name, []).append(entry)

    def inventory(self):
        rows = [{"name": name, "description": spec.description, "source": "builtin", "enabled": True, "read_only": spec.read_only, "conflict": name in self.entries} for name, spec in self.builtins.items()]
        for name, entries in sorted(self.entries.items()):
            for entry in entries:
                dist = getattr(entry, "dist", None)
                rows.append({"name": name, "description": "Installed plugin; code is loaded only on use", "source": dist.metadata.get("Name", "unknown") if dist else "unknown", "enabled": name in self.enabled, "read_only": None, "conflict": len(entries) != 1 or name in self.builtins})
        return rows

    def get(self, name):
        if name in self.builtins:
            return self.builtins[name]
        entries = self.entries.get(name, [])
        if not entries:
            raise ValueError(f"Unknown tool: {name}. Use devpocket tools list.")
        if name not in self.enabled:
            raise ValueError(f"Plugin {name} is not enabled for this project. Inspect it, then use devpocket plugins enable {name}.")
        if len(entries) != 1:
            raise ValueError(f"Multiple installed plugins claim {name}; remove the conflict before running")
        if name not in self.cache:
            factory = entries[0].load()
            spec = factory()
            if not isinstance(spec, ToolSpec) or spec.name != name:
                raise ValueError("Plugin factory must return a ToolSpec matching its entry-point name")
            self.cache[name] = spec
        return self.cache[name]
