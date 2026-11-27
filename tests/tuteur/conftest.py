"""Configure the tuteur library path for tests in this directory."""
import sys
from pathlib import Path

# Ensure src/tuteur is importable
_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# Ensure the agentic layer is importable (for test_video_script.py)
_agentic_src = _root / "backend" / "agentic" / "src"
if str(_agentic_src) not in sys.path:
    sys.path.insert(0, str(_agentic_src))
