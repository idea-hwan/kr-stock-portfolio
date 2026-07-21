"""
`stock_listing.csv` 기준 시총 상위 200종을 CSV로 보낸다.

필터·정렬은 `scripts/stock_db.py` 의 `mcap_top_n_listing_rows` 와 동일
(우선주·스팩·리츠·펀드·신탁·SPAC·KONEX·KOSDAQ GLOBAL 제외, Name 중복 시 시총 큰 행만).

출력: `stock_data/mcap_top_200.csv`

프로젝트 루트에서:
  .venv/bin/python scripts/pipeline/export_mcap_top_200.py
  .venv/bin/python scripts/pipeline/export_mcap_top_200.py --n 200 --output stock_data/mcap_top_200.csv
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
import sys

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.stock_db import mcap_top_n_listing_rows


def main() -> None:
    p = argparse.ArgumentParser(description="Export Marcap top N listing CSV")
    p.add_argument("--n", type=int, default=200, help="number of rows (default 200)")
    p.add_argument(
        "--output",
        type=Path,
        default=BASE_DIR / "stock_data" / "mcap_top_200.csv",
        help="output CSV path",
    )
    args = p.parse_args()

    df = mcap_top_n_listing_rows(args.n)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    df.to_csv(args.output, index=False)
    print(f"Wrote {len(df)} rows to {args.output}")
    print(f"generated_at_utc={gen}")


if __name__ == "__main__":
    main()
