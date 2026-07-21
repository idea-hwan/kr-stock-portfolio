"""
버킷 생존편향 교정 — 회사별 전체 히스토리를 분기(ttm_end_term)마다 롤링으로 재판정.

지금 `screen_large_growth_mcap200.py`/`screen_large_asset_mcap200.py`는 "**오늘**
기준 최근 N분기 연속 흑자"만 한 번 판정한다 — 과거엔 조건을 만족했지만 지금은
깨진 종목의 이력이 통째로 버킷 CSV에서 빠지는 생존편향이 있다.

여기서는 그 대신 **모든** (company, ttm_end_term) 조합마다 "그 시점까지의 데이터만
사용해서 최근 min_q분기가 전부 양수였는가"를 다시 계산한다 — us-stock-portfolio의
`pit_buckets16` 테이블과 동일 원칙(시점 T의 플래그는 ttm_end_term<=T 데이터만 사용,
미래 데이터 유입 없음). US 저장소엔 빌더 스크립트가 안 남아있어서(data/analytics
전체가 gitignore) 알고리즘을 리버스엔지니어링해서 포팅.

대상 유니버스: `mcap_top_200.csv` 200종목(오늘 시점 스냅샷 — 과거 시총순위 자체는
복원하지 않음. US도 동일한 한계를 그대로 받아들이고 있음).

  .venv/bin/python scripts/analysis/build_pit_buckets.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis.ttm_valuation_df import load_ttm_valuation_df
from scripts.config import PROFIT_STREAK_MIN_Q

MCAP_CSV = _ROOT / "stock_data" / "mcap_top_200.csv"
OUT_DB = _ROOT / "data" / "analytics" / "pit_buckets.db"


def rolling_all_positive(series: pd.Series, n: int) -> pd.Series:
    """각 행까지 마지막 n개(결측 포함)가 전부 >0 이면 True. n분기 미만 구간은 False."""
    positive = (series > 0).astype(float)
    positive[series.isna()] = 0.0
    roll_sum = positive.rolling(window=n, min_periods=n).sum()
    return roll_sum == n


def build_company_pit(company: str, min_q: int) -> pd.DataFrame:
    df = load_ttm_valuation_df(company)
    if df.empty:
        return pd.DataFrame()
    df = df.sort_values("ttm_end_term").reset_index(drop=True)
    growth_pit = rolling_all_positive(df["op_ps"], min_q)
    value_pit = rolling_all_positive(df["ni_parent_ps"], min_q)
    return pd.DataFrame(
        {
            "company": company,
            "ttm_end_term": df["ttm_end_term"],
            f"growth_pit{min_q}": growth_pit.astype(int),
            f"value_pit{min_q}": value_pit.astype(int),
        }
    )


def main() -> int:
    mcap = pd.read_csv(MCAP_CSV, dtype={"Code": str})
    names = [str(x).strip() for x in mcap["Name"].tolist()]

    table = f"pit_buckets{PROFIT_STREAK_MIN_Q}"
    parts: list[pd.DataFrame] = []
    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] {name}", file=sys.stderr, flush=True)
        part = build_company_pit(name, PROFIT_STREAK_MIN_Q)
        if not part.empty:
            parts.append(part)

    merged = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(OUT_DB)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    merged.to_sql(table, con, index=False)
    con.execute(f"CREATE UNIQUE INDEX idx_{table}_co_term ON {table}(company, ttm_end_term)")
    con.commit()
    con.close()

    n_companies = merged["company"].nunique() if not merged.empty else 0
    print(f"Wrote {OUT_DB}::{table}  rows={len(merged)}  companies={n_companies}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
