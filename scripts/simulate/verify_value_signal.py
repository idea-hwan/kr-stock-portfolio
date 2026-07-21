"""
대형 밸류주(large_value_stock.csv) 매수신호 재검증 — `docs/large_value_selection_strategy.md`
(run_id=1, as_of=2025Q4) 시점 수치를 최신 데이터로 재현·갱신한다.

신호: per_ratio(=op_20d/op_4y 우선, ni→rev 폴백) < 0.5 (단일 조건)

프로젝트 루트에서:
  .venv/bin/python scripts/simulate/verify_value_signal.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.simulate.signal_common import (
    bucket_stats,
    compute_per_ratio,
    load_pit_eligible_panel,
    print_stats_table,
)

CSV_PATH = _ROOT / "data" / "analytics" / "large_value_stock.csv"
PANEL_CSV = _ROOT / "data" / "analytics" / "mcap200_factor_panel.csv"
PIT_DB = _ROOT / "data" / "analytics" / "pit_buckets.db"


def main() -> None:
    df = pd.read_csv(CSV_PATH)
    df["per_ratio"] = compute_per_ratio(df)

    print(f"universe: {df['company'].nunique()}종목, {len(df)}행, term {df['ttm_end_term'].min()}~{df['ttm_end_term'].max()}")
    print()

    print("### per_ratio 구간별 12m 수익률")
    bins = [(-float("inf"), 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, float("inf"))]
    rows = []
    for lo, hi in bins:
        mask = (df["per_ratio"] >= lo) & (df["per_ratio"] < hi)
        label = f"< {hi}" if lo == -float("inf") else (f"{lo}+" if hi == float("inf") else f"{lo} ~ {hi}")
        rows.append((label, bucket_stats(df, mask)))
    print_stats_table(rows)
    print()

    print("### 현금흐름 팩터 조합 (ratio < 0.5 기준)")
    sig = df["per_ratio"] < 0.5
    cfo_bad = (df["cfo_geom_1y_mcum"] <= 0) & (df["fcf_geom_1y_mcum"] <= 0)
    cfo_good = (df["cfo_geom_1y_mcum"] > 0) & (df["fcf_geom_1y_mcum"] > 0)
    fcf_ps_bad = (df["cfo_ps"] <= 0) & (df["fcf_ps"] <= 0)
    combos = [
        ("ratio<0.5 (단독)", sig),
        ("+ cfo·fcf 성장 모두<=0", sig & cfo_bad),
        ("+ cfo·fcf 절대값 모두<=0", sig & fcf_ps_bad),
        ("+ cfo·fcf 성장 모두>0", sig & cfo_good),
    ]
    print_stats_table([(label, bucket_stats(df, mask)) for label, mask in combos])
    print()

    print("### 15m / 18m 보유기간 재확인 (핵심신호 ratio<0.5)")
    for ret_col in ("ret_12m", "ret_15m", "ret_18m"):
        s = bucket_stats(df, sig, ret_col=ret_col)
        print_stats_table([(ret_col, s)])

    print()
    print("### 종목별 현재(최신 분기) 신호 스냅샷")
    latest = df.sort_values("ttm_end_term").groupby("company").tail(1)
    latest = latest[["company", "ttm_end_term", "per_ratio", "cfo_ps", "fcf_ps"]]
    latest = latest.sort_values("per_ratio")
    with pd.option_context("display.max_rows", None, "display.width", 140):
        print(latest.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    if not (PANEL_CSV.is_file() and PIT_DB.is_file()):
        print()
        print("(PIT 교정판 스킵 — mcap200_factor_panel.csv/pit_buckets.db 없음)")
        return

    print()
    print("=" * 74)
    print("### PIT 교정판 — '오늘 통과 종목'이 아니라 '그 시점에 value_pit16=1이었던' 이벤트만")
    print("=" * 74)
    pit_df = load_pit_eligible_panel(PANEL_CSV, PIT_DB, "value_pit16")
    pit_df["per_ratio"] = compute_per_ratio(pit_df)
    print(f"PIT 이벤트: {pit_df['company'].nunique()}종목, {len(pit_df)}행 (naive: {df['company'].nunique()}종목, {len(df)}행)")
    print()

    print("### [PIT] per_ratio 구간별 12m 수익률")
    rows = []
    for lo, hi in bins:
        mask = (pit_df["per_ratio"] >= lo) & (pit_df["per_ratio"] < hi)
        label = f"< {hi}" if lo == -float("inf") else (f"{lo}+" if hi == float("inf") else f"{lo} ~ {hi}")
        rows.append((label, bucket_stats(pit_df, mask)))
    print_stats_table(rows)


if __name__ == "__main__":
    main()
