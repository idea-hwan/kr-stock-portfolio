"""
대형 성장주 매수신호 재검증 — `docs/large_growth_selection_strategy.md`의
per_ratio × acceleration 신호를 PIT 교정 유니버스(growth_pit16)로 검증한다.

버킷 조건(연속 흑자 분기 수)은 16분기로 고정한다 — 28분기와 비교한 결과 차이가 없었고
(docs/large_growth_pit_signal_verify.md), 16분기 쪽이 관측기간을 2020Q3까지 넓게 확보해
표본이 유리하다는 결론이 이미 났기 때문에 이 스크립트에서는 더 이상 28분기를 다루지 않는다.

raw 수익률과 KOSPI200 대비 alpha를 둘 다 출력한다.

확정 신호(run_id=5): 0.5 <= per_ratio(=op_20d/op_4y 우선, ni→rev 폴백) < 1.0
AND 2 <= acceleration(=op_geom_1y/op_geom_4y) < 5.
alpha mean +9.7%, median +2.1%(n=162) — 이 문서의 조합 중 mean·median이 둘 다
플러스인 유일한 신호. ratio<0.5(극단 저평가) 단독이나 accel>=2(상한 없음) 단독은
alpha 기준으로도 baseline을 못 이겨서 폐기했다 — 자세한 배경은
docs/large_growth_selection_strategy.md 참고.

프로젝트 루트에서:
  .venv/bin/python scripts/simulate/verify_growth_signal.py
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
    compute_accel,
    compute_per_ratio,
    load_pit_eligible_panel,
    print_stats_table,
)

PANEL_CSV = _ROOT / "data" / "analytics" / "mcap200_factor_panel.csv"
PIT_DB = _ROOT / "data" / "analytics" / "pit_buckets.db"
PRICES_DB = _ROOT / "data" / "analytics" / "prices.db"

RATIO_BINS = [(-float("inf"), 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, float("inf"))]
ACCEL_BINS = [(-float("inf"), 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, float("inf"))]


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
    df["accel"] = compute_accel(df)

    print(f"universe: {df['company'].nunique()}종목, {len(df)}행, term {df['ttm_end_term'].min()}~{df['ttm_end_term'].max()}")
    print()

    print("### per_ratio 구간별 12m 수익률")
    rows = [(_bin_label(lo, hi), (df["per_ratio"] >= lo) & (df["per_ratio"] < hi)) for lo, hi in RATIO_BINS]
    _print_both(df, rows)
    print()

    print("### 성장 가속 강도 구간별 (참고 — 왜 accel[2,5)만 남겼는지)")
    rows = [(_bin_label(lo, hi), (df["accel"] >= lo) & (df["accel"] < hi)) for lo, hi in ACCEL_BINS]
    _print_both(df, rows)
    print()

    print("### 확정 신호: ratio[0.5,1.0) + accel[2,5) vs 폐기된 후보들")
    accel25 = (df["accel"] >= 2) & (df["accel"] < 5)
    r_0510 = (df["per_ratio"] >= 0.5) & (df["per_ratio"] < 1.0)
    r_lt05 = df["per_ratio"] < 0.5
    combos = [
        ("확정: ratio[0.5,1) + accel[2,5)", r_0510 & accel25),
        ("폐기: ratio<0.5 (단독)", r_lt05),
        ("폐기: accel>=2 (상한없음, 단독)", df["accel"] >= 2),
        ("전체(baseline)", pd.Series(True, index=df.index)),
    ]
    _print_both(df, combos)
    print()

    print("### 15m / 18m 보유기간 (확정 신호: ratio[0.5,1) + accel[2,5))")
    sig = r_0510 & accel25
    for m in (12, 15, 18):
        _print_both(df, [(f"{m}m", sig)], ret_col=f"ret_{m}m", alpha_col=f"alpha_{m}m")


def main() -> None:
    if not (PANEL_CSV.is_file() and PIT_DB.is_file()):
        print("mcap200_factor_panel.csv / pit_buckets.db 없음")
        return
    if not PRICES_DB.is_file():
        print(f"{PRICES_DB} 없음 — KOSPI200 벤치마크 가격 필요")
        return

    df = load_pit_eligible_panel(PANEL_CSV, PIT_DB, "growth_pit16")
    df = add_benchmark_alpha(df, PRICES_DB, months_list=(12, 15, 18))

    print("=" * 74)
    print("### [PIT-16] — 그 시점까지 데이터로 16분기 연속 흑자였던 이벤트만")
    print("=" * 74)
    run_report(df)


if __name__ == "__main__":
    main()
