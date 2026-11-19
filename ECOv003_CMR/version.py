from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re

try:
    __version__ = version("ECOv003-CMR")
except PackageNotFoundError:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    __version__ = "1.3.0"
    if pyproject_path.exists():
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_path.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            __version__ = match.group(1)
