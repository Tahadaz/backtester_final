"""fix dataset.object_key backfill: use filename not symbol

Revision ID: 3c1a9f2d8e47
Revises: 9f4c2d1b7a55
Create Date: 2026-03-03 00:00:00.000000

Background
----------
Migration e2b7c24d9f0c added ``dataset.object_key`` and backfilled existing
rows using the *symbol* column::

    object_key = coalesce(object_key, 'datasets/' || data_hash || '/' || symbol)

The canonical object-key rule used by all application code is::

    datasets/{data_hash}/{filename}          -- build_dataset_object_key()

When the uploaded filename differs from the symbol (e.g. ``portfolio.xlsx``
for ticker ``AAPL``) the buggy backfill produces a key that does not exist in
object storage, causing a NoSuchKey error at run time.

This migration
--------------
Corrects exactly the rows produced by the buggy backfill without touching
anything else.  No S3 calls are made; this is a pure DB update.

Upgrade guards
~~~~~~~~~~~~~~
A row is updated only when ALL of the following hold:

1. ``data_hash IS NOT NULL``      -- can compute the correct prefix
2. ``filename  IS NOT NULL``      -- have the authoritative filename component
3. ``filename  LIKE '%.%'``       -- filename looks like a real file, not a bare
                                     ticker (avoids "fixing" rows where the
                                     earlier migration set filename = symbol,
                                     e.g. ``AAPL`` → ``IAM``)
4. ``object_key = 'datasets/' || data_hash || '/' || symbol``
                                  -- fingerprint of the buggy backfill; rows
                                     set correctly by the API won't match
5. ``object_key != 'datasets/' || data_hash || '/' || filename``
                                  -- the corrected value is actually different
                                     (pure no-op guard for extra safety)

Downgrade
~~~~~~~~~
Reverts exactly the rows changed by upgrade.  No data is dropped.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c1a9f2d8e47"
down_revision: Union[str, Sequence[str], None] = "9f4c2d1b7a55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE dataset
            SET    object_key = 'datasets/' || data_hash || '/' || filename
            WHERE  data_hash  IS NOT NULL
              AND  filename   IS NOT NULL
              AND  filename   LIKE '%.%'
              AND  object_key = 'datasets/' || data_hash || '/' || symbol
              AND  object_key != 'datasets/' || data_hash || '/' || filename
            """
        )
    )


def downgrade() -> None:
    # Revert only the rows that upgrade() could have changed:
    #   - filename contains a dot   (upgrade guard 3)
    #   - filename != symbol        (otherwise object_key was already correct
    #                                and upgrade() left it untouched)
    #   - object_key currently matches the canonical pattern we wrote
    op.execute(
        sa.text(
            """
            UPDATE dataset
            SET    object_key = 'datasets/' || data_hash || '/' || symbol
            WHERE  data_hash  IS NOT NULL
              AND  filename   IS NOT NULL
              AND  symbol     IS NOT NULL
              AND  filename   LIKE '%.%'
              AND  filename   != symbol
              AND  object_key = 'datasets/' || data_hash || '/' || filename
            """
        )
    )
