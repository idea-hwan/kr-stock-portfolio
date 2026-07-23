"""
mcap_top_200 200종목 **전체**(오늘 버킷 통과 여부 무관)의 전체 히스토리 패널.

`large_growth_stock.csv`/`large_value_stock.csv`는 "오늘 통과하는 종목만" 담고 있어서,
`pit_buckets.db`와 조인해도 "과거엔 growth/value였는데 지금은 탈락한" 종목의 이벤트
자체가 없다 — us-stock-portfolio가 `growth_stocks.csv` 단독 사용 시 PIT 이벤트
1,189개가 누락됐던 것과 같은 문제. 이 패널은 200종목 전체를 무조건 내보내서
그 문제를 없앤다. `build_pit_buckets.py`가 만든 `pit_buckets16`과
`(company, ttm_end_term)`로 조인해서 특정 시점의 growth/value 이벤트 여부를 가른다.

스키마는 다른 버킷 CSV와 동일(`stock_snapshot_core.build_stock_snapshot_df` 그대로 재사용).

주의: 종목당 라이브 가격 조회(FinanceDataReader)가 필요해서 200종목 전체 실행에
시간이 꽤 걸린다.

  .venv/bin/python scripts/analysis/build_mcap200_factor_panel.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis.ttm_valuation_df import DEFAULT_DB
from scripts.snapshot_export.stock_snapshot_core import write_universe_snapshot_csv
from scripts.snapshot_export.stock_snapshot_paths import DEFAULT_GROWTH_DB

MCAP_CSV = _ROOT / "stock_data" / "mcap_top_200.csv"
OUT_CSV = _ROOT / "data" / "analytics" / "mcap200_factor_panel.csv"


def main() -> int:
    mcap = pd.read_csv(MCAP_CSV, dtype={"Code": str})
    names = [str(x).strip() for x in mcap["Name"].tolist()]

    n_rows, n_ok, skipped = write_universe_snapshot_csv(
        names,
        OUT_CSV,
        db_path=DEFAULT_DB,
        growth_db=DEFAULT_GROWTH_DB,
        min_quarters=0,
        forward_months=[3, 6, 9, 12, 15, 18],
        anchor_term=None,
        computed_at=None,
        sleep_sec=0.0,
    )
    print(f"Wrote {OUT_CSV}  rows={n_rows}  companies_ok={n_ok}  skipped={len(skipped)}")
    if skipped:
        skip_path = OUT_CSV.with_suffix(".skipped.tsv")
        with skip_path.open("w", encoding="utf-8") as fp:
            fp.write("company\treason\n")
            for co, reason in skipped:
                fp.write(f"{co}\t{reason}\n")
        print(f"Skipped list: {skip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
