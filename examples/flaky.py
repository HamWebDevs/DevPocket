"""Alternates success/failure; stores its counter in the system temp directory."""
from pathlib import Path
import sys
import tempfile

counter = Path(tempfile.gettempdir()) / "devpocket-example-flaky-counter.txt"
try:
    previous = int(counter.read_text())
except (FileNotFoundError, ValueError):
    previous = 0
value = previous + 1
counter.write_text(str(value))
print(f"Example invocation {value}")
if value % 2:
    print("Simulated intermittent failure", file=sys.stderr)
    sys.exit(1)
print("Simulated success")
