from __future__ import annotations

from pathlib import Path

_ROOT_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if _ROOT_SCRIPTS.exists():
    __path__.append(str(_ROOT_SCRIPTS))
