"""
성장 버킷(growth_pit16, PIT 교정판) 3축 팩터 탐색 시뮬.

us-stock-portfolio의 `scripts/archive/simulate_growth_factors.py`(2026-06-22, 탐색 그리드
세대) 구조를 KR 데이터로 포팅한다 — 이후 US가 정착한 고정 단일조건(build_dashboard.py의
rev2y가속+P/OP저평가+capex1y↓)이 아니라, 그 이전 탐색 단계와 동일하게 단일→2팩터→3팩터
조합을 KOSPI200 대비 alpha 기준으로 넓게 훑어본다.

세 축:
  성장 — rev/op/ni 각각 1y↑·1y↓·2y↓·가속(1y>2y)·가속(2y>4y)  [15개]
  투자 — capex 1y↑·1y↓·2y↑·2y↓·가속(1y>2y)                    [5개]
  저평가 — P/NI·P/OP·P/rev 각각 저평가·고평가 + "P/NI 우선, 안되면
           P/OP 폴백"(표시용 val_undervalued 방식) 저평가·고평가 +
           "P/OP 우선, 안되면 P/NI, 안되면 P/rev 폴백"
           (large_growth_selection_strategy.md Signal A와 동일 우선순위) 저평가·고평가  [10개]

alpha_12m/18m = 종목 수익률 − 동일 앵커일 KOSPI200(KS200) 수익률(signal_common.add_benchmark_alpha).
KOSPI200이 삼성전자·SK하이닉스(mcap200 시총의 53.8%) 쏠림으로 왜곡됐는지는 동일가중
벤치마크와 교차검증 완료(2026-07-21) — 1위 3팩터 조합은 벤치마크를 바꿔도 견고했음.
벤치마크는 KS200(원안)으로 확정.

  .venv/bin/python scripts/simulate/growth_factor_grid.py
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
    load_pit_eligible_panel,
)

PANEL_CSV = _ROOT / "data" / "analytics" / "mcap200_factor_panel.csv"
PIT_DB = _ROOT / "data" / "analytics" / "pit_buckets.db"
PRICES_DB = _ROOT / "data" / "analytics" / "prices.db"

OUT_DIR = _ROOT / "data" / "analytics" / "simulate_results"
SINGLES_CSV = OUT_DIR / "growth_factor_grid_singles.csv"
COMBO2_CSV = OUT_DIR / "growth_factor_grid_combo2.csv"
COMBO3_CSV = OUT_DIR / "growth_factor_grid_combo3.csv"

T = 0.75  # 저평가/고평가 임계값 (US 탐색 그리드와 동일)


# ── 팩터 조건 함수 (벡터화, Series[bool] 반환) ─────────────────────────────────

def _pos(df: pd.DataFrame, col: str) -> pd.Series:
    v = df[col]
    return v.notna() & (v > 0)


def _neg(df: pd.DataFrame, col: str) -> pd.Series:
    v = df[col]
    return v.notna() & (v < 0)


def _acc(df: pd.DataFrame, fast: str, slow: str) -> pd.Series:
    a, b = df[fast], df[slow]
    return a.notna() & b.notna() & (a > b)


def _low(df: pd.DataFrame, cur: str, ref: str, t: float = T) -> pd.Series:
    c, r = df[cur], df[ref]
    return c.notna() & r.notna() & (r > 0) & (c > 0) & (c < r * t)


def _high(df: pd.DataFrame, cur: str, ref: str, t: float = T) -> pd.Series:
    c, r = df[cur], df[ref]
    return c.notna() & r.notna() & (r > 0) & (c > 0) & (c > r / t)


def _ni_priority_ratio(df: pd.DataFrame) -> pd.Series:
    """P/NI 우선, 결측/음수(적자)면 P/OP 폴백 — val_undervalued() 표시 로직과 동일 순서."""
    ni_ok = (
        df["per_ni_4y"].notna() & (df["per_ni_4y"] > 0)
        & df["per_ni_20d"].notna() & (df["per_ni_20d"] > 0)
    )
    op_ok = (
        df["per_op_4y"].notna() & (df["per_op_4y"] > 0)
        & df["per_op_20d"].notna() & (df["per_op_20d"] > 0)
    )
    use_op = (~ni_ok) & op_ok
    cur = pd.Series(float("nan"), index=df.index)
    ref = pd.Series(float("nan"), index=df.index)
    cur.loc[ni_ok] = df.loc[ni_ok, "per_ni_20d"]
    ref.loc[ni_ok] = df.loc[ni_ok, "per_ni_4y"]
    cur.loc[use_op] = df.loc[use_op, "per_op_20d"]
    ref.loc[use_op] = df.loc[use_op, "per_op_4y"]
    return cur, ref


def _ni_priority_low(df: pd.DataFrame, t: float = T) -> pd.Series:
    cur, ref = _ni_priority_ratio(df)
    return cur.notna() & (cur < ref * t)


def _ni_priority_high(df: pd.DataFrame, t: float = T) -> pd.Series:
    cur, ref = _ni_priority_ratio(df)
    return cur.notna() & (cur > ref / t)


def _op_priority_ratio(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """P/OP 우선, 안되면 P/NI, 안되면 P/rev 폴백 — signal_common.compute_per_ratio와 동일 순서
    (large_growth_selection_strategy.md Signal A 정의)."""
    cur = pd.Series(float("nan"), index=df.index)
    ref = pd.Series(float("nan"), index=df.index)
    for pair_cur, pair_ref in (("per_op_20d", "per_op_4y"), ("per_ni_20d", "per_ni_4y"), ("per_rev_20d", "per_rev_4y")):
        need = cur.isna()
        ok = need & df[pair_ref].notna() & (df[pair_ref] > 0) & df[pair_cur].notna() & (df[pair_cur] > 0)
        cur.loc[ok] = df.loc[ok, pair_cur]
        ref.loc[ok] = df.loc[ok, pair_ref]
    return cur, ref


def _op_priority_low(df: pd.DataFrame, t: float = T) -> pd.Series:
    cur, ref = _op_priority_ratio(df)
    return cur.notna() & (cur < ref * t)


def _op_priority_high(df: pd.DataFrame, t: float = T) -> pd.Series:
    cur, ref = _op_priority_ratio(df)
    return cur.notna() & (cur > ref / t)


# ── 팩터 목록 (라벨, 함수, 축) ──────────────────────────────────────────────────

FACTORS: list[tuple[str, "callable[[pd.DataFrame], pd.Series]", str]] = []

for _prefix in ("rev", "op", "ni"):
    _g1, _g2, _g4 = f"{_prefix}_geom_1y_mcum", f"{_prefix}_geom_2y_mcum", f"{_prefix}_geom_4y_mcum"
    FACTORS += [
        (f"{_prefix}_1y↑", (lambda df, c=_g1: _pos(df, c)), "성장"),
        (f"{_prefix}_1y↓", (lambda df, c=_g1: _neg(df, c)), "성장"),
        (f"{_prefix}_2y↓", (lambda df, c=_g2: _neg(df, c)), "성장"),
        (f"{_prefix}_가속(1y>2y)", (lambda df, f=_g1, s=_g2: _acc(df, f, s)), "성장"),
        (f"{_prefix}_가속(2y>4y)", (lambda df, f=_g2, s=_g4: _acc(df, f, s)), "성장"),
    ]

FACTORS += [
    ("capex_1y↑", lambda df: _pos(df, "capex_geom_1y_mcum"), "투자"),
    ("capex_1y↓", lambda df: _neg(df, "capex_geom_1y_mcum"), "투자"),
    ("capex_2y↑", lambda df: _pos(df, "capex_geom_2y_mcum"), "투자"),
    ("capex_2y↓", lambda df: _neg(df, "capex_geom_2y_mcum"), "투자"),
    ("capex_가속(1y>2y)", lambda df: _acc(df, "capex_geom_1y_mcum", "capex_geom_2y_mcum"), "투자"),
]

FACTORS += [
    ("P/NI_저평가", lambda df: _low(df, "per_ni_20d", "per_ni_4y"), "저평가"),
    ("P/NI_고평가", lambda df: _high(df, "per_ni_20d", "per_ni_4y"), "저평가"),
    ("P/OP_저평가", lambda df: _low(df, "per_op_20d", "per_op_4y"), "저평가"),
    ("P/OP_고평가", lambda df: _high(df, "per_op_20d", "per_op_4y"), "저평가"),
    ("P/rev_저평가", lambda df: _low(df, "per_rev_20d", "per_rev_4y"), "저평가"),
    ("P/rev_고평가", lambda df: _high(df, "per_rev_20d", "per_rev_4y"), "저평가"),
    ("ni우선폴백_저평가", _ni_priority_low, "저평가"),
    ("ni우선폴백_고평가", _ni_priority_high, "저평가"),
    ("op우선폴백_저평가", _op_priority_low, "저평가"),
    ("op우선폴백_고평가", _op_priority_high, "저평가"),
]

FACTOR_MAP = {lbl: fn for lbl, fn, _ in FACTORS}
FACTOR_AXIS = {lbl: axis for lbl, _, axis in FACTORS}


def apply_factor(df: pd.DataFrame, lbl: str) -> pd.Series:
    return FACTOR_MAP[lbl](df).fillna(False)


# ── 출력 헬퍼 ──────────────────────────────────────────────────────────────────

def _fmt_stat(s: dict) -> str:
    if s["n"] == 0:
        return "n=   0"
    return f"n={s['n']:4d}  mean={s['mean']:+6.1f}%  median={s['median']:+6.1f}%  >0%={s['pos']:4.0f}%"


def _row(label: str, s12: dict, s18: dict, axis: str | None = None) -> dict:
    row = {"label": label}
    if axis is not None:
        row["axis"] = axis
    for suffix, s in (("12m", s12), ("18m", s18)):
        row[f"n_{suffix}"] = s["n"]
        row[f"mean_{suffix}"] = s["mean"]
        row[f"median_{suffix}"] = s["median"]
        row[f"pos_{suffix}"] = s["pos"]
        row[f"gt20_{suffix}"] = s["gt20"]
        row[f"ltm20_{suffix}"] = s["ltm20"]
    return row


def _write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"  -> {path}  ({len(rows)}행)")


def main() -> None:
    if not (PANEL_CSV.is_file() and PIT_DB.is_file()):
        print(
            "mcap200_factor_panel.csv / pit_buckets.db 없음 — "
            "scripts/analysis/build_mcap200_factor_panel.py, scripts/analysis/build_pit_buckets.py 먼저 실행"
        )
        return
    if not PRICES_DB.is_file():
        print(f"{PRICES_DB} 없음 — KOSPI200 벤치마크 가격 필요")
        return

    df = load_pit_eligible_panel(PANEL_CSV, PIT_DB, "growth_pit16")
    df = add_benchmark_alpha(df, PRICES_DB, months_list=(12, 15, 18))

    print(
        f"growth PIT 유니버스: {df['company'].nunique()}종목, {len(df)}행, "
        f"term {df['ttm_end_term'].min()}~{df['ttm_end_term'].max()}"
    )
    base12 = bucket_stats(df, pd.Series(True, index=df.index), ret_col="alpha_12m")
    base18 = bucket_stats(df, pd.Series(True, index=df.index), ret_col="alpha_18m")
    print(f"베이스라인(전체, alpha vs KOSPI200): 12m {_fmt_stat(base12)}")
    print(f"                                   18m {_fmt_stat(base18)}\n")

    base_mean12 = base12["mean"] or 0.0

    # 1. 단일 팩터
    print("=" * 90)
    print("1. 단일 팩터 (n>=10, alpha_12m mean 내림차순)")
    print("=" * 90)
    singles = []
    for lbl, _, axis in FACTORS:
        mask = apply_factor(df, lbl)
        s12 = bucket_stats(df, mask, ret_col="alpha_12m")
        if s12["n"] >= 10:
            s18 = bucket_stats(df, mask, ret_col="alpha_18m")
            singles.append((lbl, axis, s12, s18))
    singles.sort(key=lambda x: x[2]["mean"], reverse=True)
    for lbl, axis, s12, s18 in singles:
        marker = "▲" if s12["mean"] > base_mean12 + 1 else ("▼" if s12["mean"] < base_mean12 - 1 else " ")
        a18 = f"{s18['mean']:+6.1f}%" if s18["n"] else "   —  "
        print(f"  {marker} [{axis:3s}] {lbl:20s} {_fmt_stat(s12)}  18m={a18}")
    _write_csv([_row(lbl, s12, s18, axis) for lbl, axis, s12, s18 in singles], SINGLES_CSV)

    # 2. 2팩터 조합 (다른 축)
    print()
    print("=" * 90)
    print("2. 2팩터 조합 (서로 다른 축, n>=30, base+2%p 이상, 12m mean 내림차순)")
    print("=" * 90)
    labels = [f[0] for f in FACTORS]
    combos2 = []
    for a, b in combinations(labels, 2):
        if FACTOR_AXIS[a] == FACTOR_AXIS[b]:
            continue
        mask = apply_factor(df, a) & apply_factor(df, b)
        s12 = bucket_stats(df, mask, ret_col="alpha_12m")
        if s12["n"] >= 30 and s12["mean"] is not None and s12["mean"] >= base_mean12 + 2:
            s18 = bucket_stats(df, mask, ret_col="alpha_18m")
            combos2.append((f"{a} + {b}", s12, s18))
    combos2.sort(key=lambda x: x[1]["mean"], reverse=True)
    for lbl, s12, s18 in combos2[:25]:
        a18 = f"{s18['mean']:+6.1f}%" if s18["n"] else "   —  "
        print(f"  ▲ {lbl:40s} {_fmt_stat(s12)}  18m={a18}")
    if not combos2:
        print("  (조건 만족 조합 없음)")
    else:
        print(f"  (총 {len(combos2)}개 중 상위 25개만 표시 — 전체는 CSV)")
    _write_csv([_row(lbl, s12, s18) for lbl, s12, s18 in combos2], COMBO2_CSV)

    # 3. 3팩터 조합 (축 하나씩)
    print()
    print("=" * 90)
    print("3. 3팩터 조합 (성장·투자·저평가 각 1개, n>=20, base+3%p 이상)")
    print("=" * 90)
    g_factors = [f[0] for f in FACTORS if f[2] == "성장"]
    i_factors = [f[0] for f in FACTORS if f[2] == "투자"]
    v_factors = [f[0] for f in FACTORS if f[2] == "저평가"]
    combos3 = []
    for g in g_factors:
        gm = apply_factor(df, g)
        for i in i_factors:
            im = gm & apply_factor(df, i)
            if not im.any():
                continue
            for v in v_factors:
                mask = im & apply_factor(df, v)
                s12 = bucket_stats(df, mask, ret_col="alpha_12m")
                if s12["n"] >= 20 and s12["mean"] is not None and s12["mean"] >= base_mean12 + 3:
                    s18 = bucket_stats(df, mask, ret_col="alpha_18m")
                    combos3.append((f"{g} + {i} + {v}", s12, s18))
    combos3.sort(key=lambda x: x[1]["mean"], reverse=True)
    for lbl, s12, s18 in combos3[:20]:
        a18 = f"{s18['mean']:+6.1f}%" if s18["n"] else "   —  "
        print(f"  ★ {lbl:55s} {_fmt_stat(s12)}  18m={a18}")
    if not combos3:
        print("  (조건 만족 조합 없음 — n>=20 또는 base+3%p 조건 완화 필요)")
    else:
        print(f"  (총 {len(combos3)}개 중 상위 20개만 표시 — 전체는 CSV)")
    _write_csv([_row(lbl, s12, s18) for lbl, s12, s18 in combos3], COMBO3_CSV)


if __name__ == "__main__":
    main()
