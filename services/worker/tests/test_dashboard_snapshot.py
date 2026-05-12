from __future__ import annotations

from datetime import date

from services.worker.tasks import dashboard_snapshot


class _Result:
    rowcount = 1


class _CaptureDB:
    def __init__(self):
        self.statements: list[str] = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return _Result()

    def commit(self):
        self.commits += 1


def test_snapshot_writes_jsonb_with_sqlalchemy_safe_casts() -> None:
    db = _CaptureDB()

    assert dashboard_snapshot._cas_upsert(
        db,
        "weekly",
        date(2026, 5, 9),
        {"stocks": []},
        {"revision_key": "2026-05-09"},
    )
    dashboard_snapshot._write_pipeline_revision(
        db,
        "weekly",
        {"revision_key": "2026-05-09"},
        {"stocks": []},
    )

    sql = "\n".join(db.statements)
    assert "CAST(:payload AS jsonb)" in sql
    assert "CAST(:upstream_rev AS jsonb)" in sql
    assert ":payload::jsonb" not in sql
    assert ":upstream_rev::jsonb" not in sql
    assert db.commits == 2
