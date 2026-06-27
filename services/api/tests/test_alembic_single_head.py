"""Regression guard: Alembic migration tree must have exactly one head.

Multi-head trees cause `alembic upgrade head` to fail on a fresh database
(ambiguous target), breaking clean-clone deployments.  This test uses the
Alembic Python API against the on-disk versions/ directory — no database
connection required — so it runs in any CI environment.

If this test fails, generate a merge revision:
    cd services/api
    alembic merge -m "merge N heads into single tip" <rev1> <rev2> ...
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_exactly_one_head() -> None:
    ini_path = Path(__file__).parents[1] / "alembic.ini"
    cfg = Config(str(ini_path))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, (
        f"Alembic migration tree has {len(heads)} heads — expected exactly 1.\n"
        f"Heads: {heads}\n"
        "Fix: cd services/api && alembic merge -m 'merge N heads' <rev1> <rev2> ..."
    )
