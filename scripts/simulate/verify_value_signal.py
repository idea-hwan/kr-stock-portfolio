"""
대형 밸류주 매수신호 재검증 — PIT 교정 유니버스(value_pit16)로 per_ratio 단일 신호를
KOSPI200 대비 alpha 기준으로 검증한다.

value_pit16 = 그 시점까지 최근 16분기 연속 ni_parent_ps(순이익) > 0 (build_pit_buckets.py).
growth_pit16(영업이익 연속흑자)과 조건 축만 다르고 나머지(시총 top200, 유틸리티·지주회사
제외, 롤링 PIT 재판정)는 동일 — docs/large_growth_selection_strategy.md §2 참고.

per_ratio 정의는 growth와 동일(op_20d/op_4y 우선, ni→rev 폴백, signal_common.compute_per_ratio)
— 옛 large_value_selection_strategy.md(삭제됨, run_id=1, PIT 교정 전) 정의를 그대로 승계.
가속(acceleration) 축은 쓰지 않는다 — 밸류 버킷은 "성장"이 아니라 "얼마나 싼가"만 본다.

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
    add_benchmark_alpha,
    bucket_stats,
    compute_per_ratio,
    load_pit_eligible_panel,
    print_stats_table,
)

PANEL_CSV = _ROOT / "data" / "analytics" / "mcap200_factor_panel.csv"
PIT_DB = _ROOT / "data" / "analytics" / "pit_buckets.db"
PRICES_DB = _ROOT / "data" / "analytics" / "prices.db"

RATIO_BINS = [(-float("inf"), 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, float("inf"))]


def _bin_label(lo: float, hi: float) -> str:
    if lo == -float("inf"):
        return f"< {hi}"
    if hi == float("inf"):
        return f"{lo}+"
    return f"{lo} ~ {hi}"


def _print_both(df: pd.DataFrame, rows: list[tuple[str, pd.Series]], ret_col: str = "ret_12m", alpha_col: str = "alpha_12m") -> None:
    print(f"-- raw ({ret_col}) --")
    print_stats_table([(label, bucket_stats(df, mask, ret_col=ret_col)) for label, mask in rows])
    print(f"-- alpha vs KOSPI200 ({alpha_col}) --")
    print_stats_table([(label, bucket_stats(df, mask, ret_col=alpha_col)) for label, mask in rows])


def run_report(df: pd.DataFrame) -> None:
    df = df.copy()
    df["per_ratio"] = compute_per_ratio(df)

    print(f"universe: {df['company'].nunique()}종목, {len(df)}행, term {df['ttm_end_term'].min()}~{df['ttm_end_term'].max()}")
    print()

    print("### per_ratio 구간별 12m 수익률 (raw / alpha)")
    rows = [(_bin_label(lo, hi), (df["per_ratio"] >= lo) & (df["per_ratio"] < hi)) for lo, hi in RATIO_BINS]
    _print_both(df, rows)
    print()

    print("### 옛 신호(ratio<0.5, PIT 교정 전 run_id=1) vs 전체")
    r_lt05 = df["per_ratio"] < 0.5
    combos = [
        ("옛 신호: ratio<0.5 (단독)", r_lt05),
        ("전체(baseline)", pd.Series(True, index=df.index)),
    ]
    _print_both(df, combos)
    print()

    print("### 현금흐름 팩터 조합 참고 (ratio<0.5 기준)")
    cfo_bad = (df["cfo_geom_1y_mcum"] <= 0) & (df["fcf_geom_1y_mcum"] <= 0)
    cfo_good = (df["cfo_geom_1y_mcum"] > 0) & (df["fcf_geom_1y_mcum"] > 0)
    combos = [
        ("ratio<0.5 + cfo·fcf 성장 모두<=0", r_lt05 & cfo_bad),
        ("ratio<0.5 + cfo·fcf 성장 모두>0", r_lt05 & cfo_good),
    ]
    _print_both(df, combos)
    print()

    print("### 15m / 18m 보유기간 (ratio<0.5)")
    for m in (12, 15, 18):
        _print_both(df, [(f"{m}m", r_lt05)], ret_col=f"ret_{m}m", alpha_col=f"alpha_{m}m")


def main() -> None:
    if not (PANEL_CSV.is_file() and PIT_DB.is_file()):
        print("mcap200_factor_panel.csv / pit_buckets.db 없음")
        return
    if not PRICES_DB.is_file():
        print(f"{PRICES_DB} 없음 — KOSPI200 벤치마크 가격 필요")
        return

    df = load_pit_eligible_panel(PANEL_CSV, PIT_DB, "value_pit16")
    df = add_benchmark_alpha(df, PRICES_DB, months_list=(12, 15, 18))

    print("=" * 74)
    print("### [PIT-16] — 그 시점까지 데이터로 16분기 연속 순이익 흑자였던 이벤트만")
    print("=" * 74)
    run_report(df)


if __name__ == "__main__":
    main()
