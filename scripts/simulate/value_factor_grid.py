"""
밸류 버킷(value_pit16, PIT 교정판) 저평가×품질 2축 팩터 탐색 시뮬.

verify_value_signal.py로 per_ratio 단일 신호(옛 run_id=1: ratio<0.5)를 재검증한 결과,
PIT 교정 + 유틸리티·지주회사 제외 유니버스에서는 **어느 ratio 구간도 mean·median이
둘 다 플러스가 아니었다** — growth와 달리 "얼마나 싼가"만으로는 신호가 안 선다.
이 스크립트는 growth_factor_grid.py와 같은 방식으로 저평가(per_ratio 구간) ×
품질(rev/op/cfo/fcf 1y 방향) 조합을 KOSPI200 대비 alpha로 넓게 훑어 "싸기만 한 게
아니라 현금흐름·이익 질까지 되는" 조합이 있는지 찾는다.

두 축:
  저평가 — per_ratio(op→ni→rev 우선폴백) 구간 5개: <0.5, [0.5,1.0), [1.0,1.5), [1.5,2.0), 2.0+
  품질   — rev/op/cfo/fcf 각각 1y>0, 1y<=0  [8개] + 전부>0 조합 1개

  .venv/bin/python scripts/simulate/value_factor_grid.py
"""

from __future__ import annotations

import sys
from itertools import combinations
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
)

PANEL_CSV = _ROOT / "data" / "analytics" / "mcap200_factor_panel.csv"
PIT_DB = _ROOT / "data" / "analytics" / "pit_buckets.db"
PRICES_DB = _ROOT / "data" / "analytics" / "prices.db"

OUT_DIR = _ROOT / "data" / "analytics" / "simulate_results"
SINGLES_CSV = OUT_DIR / "value_factor_grid_singles.csv"
COMBO2_CSV = OUT_DIR / "value_factor_grid_combo2.csv"

RATIO_BINS = [(-float("inf"), 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, float("inf"))]


def _bin_label(lo: float, hi: float) -> str:
    if lo == -float("inf"):
        return f"ratio<{hi}"
    if hi == float("inf"):
        return f"ratio>={lo}"
    return f"ratio[{lo},{hi})"


def _pos(df: pd.DataFrame, col: str) -> pd.Series:
    v = df[col]
    return v.notna() & (v > 0)


def _neg_or_na(df: pd.DataFrame, col: str) -> pd.Series:
    v = df[col]
    return ~(v.notna() & (v > 0))


QUALITY_FACTORS: list[tuple[str, "callable[[pd.DataFrame], pd.Series]"]] = []
for _prefix in ("rev", "op", "cfo", "fcf"):
    _g1 = f"{_prefix}_geom_1y_mcum"
    QUALITY_FACTORS.append((f"{_prefix}_1y>0", lambda df, c=_g1: _pos(df, c)))
    QUALITY_FACTORS.append((f"{_prefix}_1y<=0", lambda df, c=_g1: _neg_or_na(df, c)))

QUALITY_MAP = {lbl: fn for lbl, fn in QUALITY_FACTORS}


def _fmt_stat(s: dict) -> str:
    if s["n"] == 0:
        return "n=   0"
    return f"n={s['n']:4d}  mean={s['mean']:+6.1f}%  median={s['median']:+6.1f}%  >0%={s['pos']:4.0f}%"


def _row(label: str, s12: dict, s18: dict) -> dict:
    row = {"label": label}
    for suffix, s in (("12m", s12), ("18m", s18)):
        row[f"n_{suffix}"] = s["n"]
        row[f"mean_{suffix}"] = s["mean"]
        row[f"median_{suffix}"] = s["median"]
        row[f"pos_{suffix}"] = s["pos"]
    return row


def _write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"  -> {path}  ({len(rows)}행)")


def main() -> None:
    if not (PANEL_CSV.is_file() and PIT_DB.is_file()):
        print("mcap200_factor_panel.csv / pit_buckets.db 없음")
        return
    if not PRICES_DB.is_file():
        print(f"{PRICES_DB} 없음 — KOSPI200 벤치마크 가격 필요")
        return

    df = load_pit_eligible_panel(PANEL_CSV, PIT_DB, "value_pit16")
    df["per_ratio"] = compute_per_ratio(df)
    df = add_benchmark_alpha(df, PRICES_DB, months_list=(12, 15, 18))

    print(f"value PIT 유니버스: {df['company'].nunique()}종목, {len(df)}행, term {df['ttm_end_term'].min()}~{df['ttm_end_term'].max()}")
    base12 = bucket_stats(df, pd.Series(True, index=df.index), ret_col="alpha_12m")
    print(f"베이스라인(전체, alpha vs KOSPI200): 12m {_fmt_stat(base12)}\n")
    base_mean12 = base12["mean"] or 0.0

    ratio_masks = [(_bin_label(lo, hi), (df["per_ratio"] >= lo) & (df["per_ratio"] < hi)) for lo, hi in RATIO_BINS]

    # 1. ratio 구간 단독 (참고, verify_value_signal.py와 동일 결과 재확인용)
    print("=" * 90)
    print("1. ratio 구간 단독 (참고)")
    print("=" * 90)
    singles = []
    for lbl, mask in ratio_masks:
        s12 = bucket_stats(df, mask, ret_col="alpha_12m")
        s18 = bucket_stats(df, mask, ret_col="alpha_18m")
        singles.append((lbl, s12, s18))
        both_pos = s12["mean"] is not None and s12["mean"] > 0 and s12["median"] is not None and s12["median"] > 0
        marker = "✓" if both_pos else " "
        print(f"  {marker} {lbl:16s} {_fmt_stat(s12)}")
    _write_csv([_row(lbl, s12, s18) for lbl, s12, s18 in singles], SINGLES_CSV)

    # 2. ratio 구간 × 품질 팩터 조합 (mean·median 둘 다 플러스만 표시)
    print()
    print("=" * 90)
    print("2. ratio 구간 × 품질 팩터 (n>=15, alpha_12m mean·median 둘 다 플러스만)")
    print("=" * 90)
    combos = []
    for rlbl, rmask in ratio_masks:
        for qlbl, qfn in QUALITY_FACTORS:
            mask = rmask & qfn(df).fillna(False)
            s12 = bucket_stats(df, mask, ret_col="alpha_12m")
            if s12["n"] >= 15 and s12["mean"] is not None and s12["mean"] > 0 and s12["median"] is not None and s12["median"] > 0:
                s18 = bucket_stats(df, mask, ret_col="alpha_18m")
                combos.append((f"{rlbl} + {qlbl}", s12, s18))
    # 3. ratio 구간 × 품질 2팩터 조합 (다른 지표)
    q_labels = [f[0] for f in QUALITY_FACTORS]
    for rlbl, rmask in ratio_masks:
        for a, b in combinations(q_labels, 2):
            pa, pb = a.split("_")[0], b.split("_")[0]
            if pa == pb:
                continue
            mask = rmask & QUALITY_MAP[a](df).fillna(False) & QUALITY_MAP[b](df).fillna(False)
            s12 = bucket_stats(df, mask, ret_col="alpha_12m")
            if s12["n"] >= 15 and s12["mean"] is not None and s12["mean"] > 0 and s12["median"] is not None and s12["median"] > 0:
                s18 = bucket_stats(df, mask, ret_col="alpha_18m")
                combos.append((f"{rlbl} + {a} + {b}", s12, s18))

    combos.sort(key=lambda x: x[1]["mean"], reverse=True)
    if not combos:
        print("  (mean·median 둘 다 플러스인 조합 없음)")
    for lbl, s12, s18 in combos[:30]:
        a18 = f"{s18['mean']:+6.1f}%/{s18['median']:+6.1f}%" if s18["n"] else "  —"
        print(f"  ✓ {lbl:40s} {_fmt_stat(s12)}  18m(mean/median)={a18}")
    _write_csv([_row(lbl, s12, s18) for lbl, s12, s18 in combos], COMBO2_CSV)


if __name__ == "__main__":
    main()
