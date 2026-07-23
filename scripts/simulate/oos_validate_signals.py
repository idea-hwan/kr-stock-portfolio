"""
확정 신호 4개(대형 성장주/밸류주 × 매수/매도) out-of-sample 검증.

네 신호 모두 growth_pit16·value_pit16 전체 기간(2020Q3~2026Q1, 23분기)을 한 번에 써서
그리드서치·검증했다 — 즉 "가장 잘 나온 조합을 고른" 표본과 "성과를 평가한" 표본이 완전히
같다(선택 편향/과적합 위험). 새 미래 데이터가 쌓이길 기다릴 수는 없으니, 대신 기존 기간을
전반(train, 2020Q3~2023Q2, 12분기)과 후반(test, 2023Q3~2026Q1, 11분기)으로 쪼개
"이미 확정한 공식"이 두 구간 모두에서 같은 방향(매수=플러스, 매도=마이너스)으로 성립하는지
확인한다. 진짜 walk-forward(= train 구간만으로 그리드서치를 다시 돌려 같은 공식이 나오는지)는
아니고, split-half 안정성 체크다 — 특정 분기·국면에만 의존한 우연이 아닌지 보는 것이 목적.

  .venv/bin/python scripts/simulate/oos_validate_signals.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.simulate.signal_common import add_benchmark_alpha, bucket_stats, compute_accel, compute_per_ratio, load_pit_eligible_panel

PANEL_CSV = _ROOT / "data" / "analytics" / "mcap200_factor_panel.csv"
PIT_DB = _ROOT / "data" / "analytics" / "pit_buckets.db"
PRICES_DB = _ROOT / "data" / "analytics" / "prices.db"

TRAIN_TERMS_END = "2023Q2"  # train: ~term <= 2023Q2 (12분기) / test: term > 2023Q2 (11분기)


def _split(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    train = df["ttm_end_term"] <= TRAIN_TERMS_END
    return train, ~train


def _fmt(s: dict) -> str:
    if s["n"] == 0:
        return "n=   0"
    return f"n={s['n']:4d}  mean={s['mean']:+6.1f}%  median={s['median']:+6.1f}%  >0%={s['pos']:4.0f}%"


def _report(name: str, df: pd.DataFrame, sig: pd.Series, ret_cols: list[str], expect_positive: bool) -> None:
    print("=" * 90)
    print(f"{name}  (기대 방향: {'플러스(매수)' if expect_positive else '마이너스(매도)'})")
    print("=" * 90)
    train, test = _split(df)
    for label, period_mask in (("전체", pd.Series(True, index=df.index)), ("train(~2023Q2)", train), ("test(2023Q3~)", test)):
        m = sig & period_mask
        row = []
        ok_all = True
        for rc in ret_cols:
            s = bucket_stats(df, m, ret_col=rc)
            row.append(f"{rc.replace('alpha_','')}: {_fmt(s)}")
            if s["n"] > 0 and s["mean"] is not None:
                sign_ok = (s["mean"] > 0) if expect_positive else (s["mean"] < 0)
                ok_all = ok_all and sign_ok
        marker = "✓" if ok_all else "✗"
        print(f"  [{label:14s}] {marker}  " + "   ".join(row))
    print()


def main() -> None:
    if not (PANEL_CSV.is_file() and PIT_DB.is_file() and PRICES_DB.is_file()):
        print("mcap200_factor_panel.csv / pit_buckets.db / prices.db 없음")
        return

    # ── 성장주 ──────────────────────────────────────────────────────────────
    g = load_pit_eligible_panel(PANEL_CSV, PIT_DB, "growth_pit16")
    g = add_benchmark_alpha(g, PRICES_DB, months_list=(3, 6, 9, 12))
    g["per_ratio"] = compute_per_ratio(g)
    g["accel"] = compute_accel(g)

    g_buy = (g["per_ratio"] >= 0.5) & (g["per_ratio"] < 1.0) & (g["accel"] >= 2) & (g["accel"] < 5)
    _report("성장주 매수 (run_id=5): ratio[0.5,1.0) + accel[2,5)", g, g_buy, ["alpha_12m"], True)

    g_sell = (
        g["ni_geom_1y_mcum"].notna() & (g["ni_geom_1y_mcum"] < 0)
        & g["cfo_geom_1y_mcum"].notna() & (g["cfo_geom_1y_mcum"] < 0)
        & g["per_ni_4y"].notna() & (g["per_ni_4y"] > 0)
        & g["per_ni_20d"].notna() & (g["per_ni_20d"] > 0)
        & (g["per_ni_20d"] / g["per_ni_4y"] > 1.25)
    )
    _report(
        "성장주 매도 (run_id=6): ni_1y↓ + cfo_1y↓ + P/NI 고평가(>1.25)",
        g, g_sell, ["alpha_3m", "alpha_6m", "alpha_9m", "alpha_12m"], False,
    )

    # ── 밸류주 ──────────────────────────────────────────────────────────────
    v = load_pit_eligible_panel(PANEL_CSV, PIT_DB, "value_pit16")
    v = add_benchmark_alpha(v, PRICES_DB, months_list=(3, 6, 9, 12))
    v["per_ratio"] = compute_per_ratio(v)

    v_buy = (v["per_ratio"] < 0.5) & v["op_geom_1y_mcum"].notna() & (v["op_geom_1y_mcum"] > 0)
    _report("밸류주 매수 (run_id=2): ratio<0.5 + op_1y>0", v, v_buy, ["alpha_12m"], True)

    v_sell = (
        v["ni_geom_1y_mcum"].notna() & (v["ni_geom_1y_mcum"] < 0)
        & v["cfo_geom_1y_mcum"].notna() & (v["cfo_geom_1y_mcum"] < 0)
        & v["per_ni_4y"].notna() & (v["per_ni_4y"] > 0)
        & v["per_ni_20d"].notna() & (v["per_ni_20d"] > 0)
        & (v["per_ni_20d"] / v["per_ni_4y"] > 1.25)
    )
    _report(
        "밸류주 매도 (run_id=3): ni_1y↓ + cfo_1y↓ + P/NI 고평가(>1.25)",
        v, v_sell, ["alpha_3m", "alpha_6m", "alpha_9m", "alpha_12m"], False,
    )


if __name__ == "__main__":
    main()
