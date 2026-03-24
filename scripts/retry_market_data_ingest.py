from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.worker.tasks.ingest_market_data import ingest_excel_to_store


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-run Excel ingest for one or more existing dataset IDs."
    )
    parser.add_argument("dataset_ids", nargs="+", help="Dataset UUID(s) to re-ingest")
    args = parser.parse_args()

    for dataset_id in args.dataset_ids:
        result: dict[str, Any] = ingest_excel_to_store(dataset_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
