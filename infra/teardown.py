"""Show the owned-resource teardown plan; --execute performs it."""

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    raise SystemExit(subprocess.call([
        sys.executable, str(Path(__file__).with_name("provision.py")), "down", *sys.argv[1:],
    ]))
