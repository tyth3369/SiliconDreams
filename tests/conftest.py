"""Global test isolation configured before application modules are imported."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_runtime_dir = Path(tempfile.mkdtemp(prefix="silicondreams-pytest-"))
os.environ["SILICONDREAMS_DATABASE_FILE"] = str(_runtime_dir / "suite.db")
atexit.register(shutil.rmtree, _runtime_dir, ignore_errors=True)
