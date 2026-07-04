from __future__ import annotations

import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.services.fundamentals import (
    _load_period_history,
    period_metric_rows_for_symbol,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def _make_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.Dataset.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalPeriodMetric.__table__,
    ):
        table.create(engine)
    return SessionLocal(), engine


def test_cross_import_merge_exposes_sub_annual_rows_from_older_import() -> None:
    db, engine = _make_session()
    try:
        older_import = models.FundamentalImport(
            filename="bvc_targeted.json",
            source_hash="older-hash",
            status="succeeded",
            data_source="targeted_bvc",
            created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        )
        newer_import = models.FundamentalImport(
            filename="workbook.xlsx",
            source_hash="newer-hash",
            status="succeeded",
            created_at=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
        )
        db.add_all([older_import, newer_import])
        db.flush()

        db.add(
            models.FundamentalPeriodMetric(
                import_id=older_import.id,
                symbol="AAA",
                company_name="Alpha",
                fiscal_year=2025,
                period_type="quarterly",
                period_label="Q1",
                metric_name="Revenue",
                metric_value=100.0,
            )
        )
        db.commit()

        history = _load_period_history(db, newer_import.id, symbol="AAA")
        assert len(history) == 1
        assert history[0].period_type == "quarterly"
        assert history[0].fiscal_year == 2025
        assert history[0].metric_value == 100.0

        rows = period_metric_rows_for_symbol(db, import_id=newer_import.id, symbol="AAA")
        assert len(rows) == 1
        assert rows[0].import_id == older_import.id
    finally:
        db.close()
        engine.dispose()


def test_preference_order_requested_import_then_non_proxy_then_newest() -> None:
    db, engine = _make_session()
    try:
        requested_import = models.FundamentalImport(
            filename="requested.xlsx",
            source_hash="requested-hash",
            status="succeeded",
            created_at=dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc),
        )
        newer_other_import = models.FundamentalImport(
            filename="newer.json",
            source_hash="newer-hash",
            status="succeeded",
            created_at=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
        )
        older_other_import = models.FundamentalImport(
            filename="older.json",
            source_hash="older-hash",
            status="succeeded",
            created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        )
        db.add_all([requested_import, newer_other_import, older_other_import])
        db.flush()

        # Case 1: requested import wins even though another import is newer / non-proxy.
        db.add(
            models.FundamentalPeriodMetric(
                import_id=requested_import.id,
                symbol="AAA",
                company_name="Alpha",
                fiscal_year=2025,
                period_type="quarterly",
                period_label="Q1",
                metric_name="Revenue",
                metric_value=111.0,
                is_proxy=False,
            )
        )
        db.add(
            models.FundamentalPeriodMetric(
                import_id=newer_other_import.id,
                symbol="AAA",
                company_name="Alpha",
                fiscal_year=2025,
                period_type="quarterly",
                period_label="Q1",
                metric_name="Revenue",
                metric_value=222.0,
                is_proxy=False,
            )
        )

        # Case 2: no row from requested import -> prefer non-proxy over proxy, even if
        # the proxy row is in a newer import.
        db.add(
            models.FundamentalPeriodMetric(
                import_id=older_other_import.id,
                symbol="AAA",
                company_name="Alpha",
                fiscal_year=2025,
                period_type="quarterly",
                period_label="Q2",
                metric_name="Revenue",
                metric_value=333.0,
                is_proxy=False,
            )
        )
        db.add(
            models.FundamentalPeriodMetric(
                import_id=newer_other_import.id,
                symbol="AAA",
                company_name="Alpha",
                fiscal_year=2025,
                period_type="quarterly",
                period_label="Q2",
                metric_name="Revenue",
                metric_value=444.0,
                is_proxy=True,
            )
        )

        # Case 3: both non-proxy, neither in requested import -> prefer newest import.
        db.add(
            models.FundamentalPeriodMetric(
                import_id=older_other_import.id,
                symbol="AAA",
                company_name="Alpha",
                fiscal_year=2025,
                period_type="quarterly",
                period_label="Q3",
                metric_name="Revenue",
                metric_value=555.0,
                is_proxy=False,
            )
        )
        db.add(
            models.FundamentalPeriodMetric(
                import_id=newer_other_import.id,
                symbol="AAA",
                company_name="Alpha",
                fiscal_year=2025,
                period_type="quarterly",
                period_label="Q3",
                metric_name="Revenue",
                metric_value=666.0,
                is_proxy=False,
            )
        )
        db.commit()

        history = {
            (row.fiscal_year, row.period_label): row.metric_value
            for row in _load_period_history(db, requested_import.id, symbol="AAA")
        }
        assert history[(2025, "Q1")] == 111.0
        assert history[(2025, "Q2")] == 333.0
        assert history[(2025, "Q3")] == 666.0
    finally:
        db.close()
        engine.dispose()


def test_s1_h1_period_label_collision_dedupes_to_one_row() -> None:
    db, engine = _make_session()
    try:
        import_a = models.FundamentalImport(
            filename="a.json",
            source_hash="a-hash",
            status="succeeded",
            created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        )
        import_b = models.FundamentalImport(
            filename="b.json",
            source_hash="b-hash",
            status="succeeded",
            created_at=dt.datetime(2026, 2, 1, tzinfo=dt.timezone.utc),
        )
        db.add_all([import_a, import_b])
        db.flush()

        db.add(
            models.FundamentalPeriodMetric(
                import_id=import_a.id,
                symbol="AAA",
                company_name="Alpha",
                fiscal_year=2025,
                period_type="semiannual",
                period_label="S1",
                metric_name="Revenue",
                metric_value=1000.0,
                is_proxy=False,
            )
        )
        db.add(
            models.FundamentalPeriodMetric(
                import_id=import_b.id,
                symbol="AAA",
                company_name="Alpha",
                fiscal_year=2025,
                period_type="semiannual",
                period_label="H1",
                metric_name="Revenue",
                metric_value=1000.0,
                is_proxy=False,
            )
        )
        db.commit()

        history = _load_period_history(db, import_b.id, symbol="AAA")
        assert len(history) == 1
        assert history[0].period_label == "H1"

        rows = period_metric_rows_for_symbol(db, import_id=import_b.id, symbol="AAA")
        assert len(rows) == 1
        # Requested import (import_b) wins the H1/S1 collision.
        assert rows[0].import_id == import_b.id
        assert rows[0].period_label == "H1"
    finally:
        db.close()
        engine.dispose()
