import tempfile
from pathlib import Path
import unittest
from devpocket.sdk import ToolContext
from devpocket_plugin_long_lines import build_tool

class PluginTests(unittest.TestCase):
    def test_detects_long_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "sample.txt").write_text("abcdefghij\n", encoding="utf-8")
            result = build_tool().run(ToolContext(root), {"path": "sample.txt", "max_length": 5})
            self.assertEqual(len(result.findings), 1)

if __name__ == "__main__":
    unittest.main()
