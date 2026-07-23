"""
밸류 버킷(value_pit16, PIT 교정판) 매도 신호 3축 팩터 탐색 시뮬.

growth_sell_factor_grid.py와 동일한 방법론(us-stock-portfolio 이식, 3축 그리드서치,
3/6/9개월 alpha)을 value_pit16에 적용한다. 매수 신호(large_value_selection_strategy.md
§3: ratio<0.5 AND op_1y>0)와 대칭으로, "싸 보이던 종목이 실제로 무너지는" 조합을 찾는다.

세 축:
  성장 꺾임 — op/rev/ni 각각 1y↓·2y↓·가속둔화(1y<2y)·2y_가속둔화(2y<4y), fcf_가속둔화(1y<2y)
  고평가   — P/OP·P/NI·P/rev·P/FCF 20일 vs 4년 평균, 고평가만(T=1.25)
  투자압박 — fcf_1y↓, capex_1y↑, capex_가속(1y>2y), cfo_1y↓

  .venv/bin/python scripts/simulate/value_sell_factor_grid.py
"""

from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.simulate.signal_common import add_benchmark_alpha, bucket_stats, load_pit_eligible_panel

PANEL_CSV = _ROOT / "data" / "analytics" / "mcap200_factor_panel.csv"
PIT_DB = _ROOT / "data" / "analytics" / "pit_buckets.db"
PRICES_DB = _ROOT / "data" / "analytics" / "prices.db"

OUT_DIR = _ROOT / "data" / "analytics" / "scratch" / "simulate_results"
SINGLES_CSV = OUT_DIR / "value_sell_factor_grid_singles.csv"
COMBO2_CSV = OUT_DIR / "value_sell_factor_grid_combo2.csv"
COMBO3_CSV = OUT_DIR / "value_sell_factor_grid_combo3.csv"

T_HIGH = 1.25
MONTHS = (3, 6, 9, 12)
PRIMARY = "alpha_3m"


def _neg(df: pd.DataFrame, col: str) -> pd.Series:
    v = df[col]
    return v.notna() & (v < 0)


def _pos(df: pd.DataFrame, col: str) -> pd.Series:
    v = df[col]
    return v.notna() & (v > 0)


def _dec(df: pd.DataFrame, fast: str, slow: str) -> pd.Series:
    a, b = df[fast], df[slow]
    return a.notna() & b.notna() & (a < b)


def _acc(df: pd.DataFrame, fast: str, slow: str) -> pd.Series:
    a, b = df[fast], df[slow]
    return a.notna() & b.notna() & (a > b)


def _high(df: pd.DataFrame, cur: str, ref: str, t: float = T_HIGH) -> pd.Series:
    c, r = df[cur], df[ref]
    return c.notna() & r.notna() & (r > 0) & (c > 0) & (c / r > t)


FACTORS: list[tuple[str, "callable[[pd.DataFrame], pd.Series]", str]] = []

for _prefix in ("op", "rev", "ni"):
    _g1, _g2, _g4 = f"{_prefix}_geom_1y_mcum", f"{_prefix}_geom_2y_mcum", f"{_prefix}_geom_4y_mcum"
    FACTORS += [
        (f"{_prefix}_1y↓", (lambda df, c=_g1: _neg(df, c)), "성장꺾임"),
        (f"{_prefix}_2y↓", (lambda df, c=_g2: _neg(df, c)), "성장꺾임"),
        (f"{_prefix}_dec(1y<2y)", (lambda df, f=_g1, s=_g2: _dec(df, f, s)), "성장꺾임"),
        (f"{_prefix}_2y_dec(2y<4y)", (lambda df, f=_g2, s=_g4: _dec(df, f, s)), "성장꺾임"),
    ]
FACTORS.append(
    ("fcf_dec(1y<2y)", lambda df: _dec(df, "fcf_geom_1y_mcum", "fcf_geom_2y_mcum"), "성장꺾임")
)

FACTORS += [
    ("P/OP_고평가", lambda df: _high(df, "per_op_20d", "per_op_4y"), "고평가"),
    ("P/NI_고평가", lambda df: _high(df, "per_ni_20d", "per_ni_4y"), "고평가"),
    ("P/rev_고평가", lambda df: _high(df, "per_rev_20d", "per_rev_4y"), "고평가"),
    ("P/FCF_고평가", lambda df: _high(df, "per_fcf_20d", "per_fcf_4y"), "고평가"),
]

FACTORS += [
    ("fcf_1y↓", lambda df: _neg(df, "fcf_geom_1y_mcum"), "투자압박"),
    ("capex_1y↑", lambda df: _pos(df, "capex_geom_1y_mcum"), "투자압박"),
    ("capex_가속(1y>2y)", lambda df: _acc(df, "capex_geom_1y_mcum", "capex_geom_2y_mcum"), "투자압박"),
    ("cfo_1y↓", lambda df: _neg(df, "cfo_geom_1y_mcum"), "투자압박"),
]

FACTOR_MAP = {lbl: fn for lbl, fn, _ in FACTORS}
FACTOR_AXIS = {lbl: axis for lbl, _, axis in FACTORS}


def apply_factor(df: pd.DataFrame, lbl: str) -> pd.Series:
    return FACTOR_MAP[lbl](df).fillna(False)


def _fmt_stat(s: dict) -> str:
    if s["n"] == 0:
        return "n=   0"
    return f"n={s['n']:4d}  mean={s['mean']:+6.1f}%  median={s['median']:+6.1f}%  >0%={s['pos']:4.0f}%"


def _all_stats(df: pd.DataFrame, mask: pd.Series) -> dict[str, dict]:
    return {f"alpha_{m}m": bucket_stats(df, mask, ret_col=f"alpha_{m}m") for m in MONTHS}


def _row(label: str, stats: dict[str, dict], axis: str | None = None) -> dict:
    row = {"label": label}
    if axis is not None:
        row["axis"] = axis
    for key, s in stats.items():
        row[f"n_{key}"] = s["n"]
        row[f"mean_{key}"] = s["mean"]
        row[f"median_{key}"] = s["median"]
        row[f"pos_{key}"] = s["pos"]
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

    df = load_pit_eligible_panel(PANEL_CSV, PIT_DB, "value_pit16")
    missing_ret = [f"ret_{m}m" for m in MONTHS if f"ret_{m}m" not in df.columns]
    if missing_ret:
        print(f"패널에 {missing_ret} 없음 — build_mcap200_factor_panel.py를 forward_months=[3,6,9,12,15,18]로 재생성 필요")
        return
    df = add_benchmark_alpha(df, PRICES_DB, months_list=MONTHS)

    print(
        f"value PIT 유니버스: {df['company'].nunique()}종목, {len(df)}행, "
        f"term {df['ttm_end_term'].min()}~{df['ttm_end_term'].max()}"
    )
    base = _all_stats(df, pd.Series(True, index=df.index))
    for m in MONTHS:
        print(f"베이스라인 alpha_{m}m: {_fmt_stat(base[f'alpha_{m}m'])}")
    print(f"P/FCF 결측 제외 후 표본: {df['per_fcf_20d'].notna().sum()}/{len(df)}행\n")

    base_primary = base[PRIMARY]["mean"] or 0.0

    print("=" * 100)
    print(f"1. 단일 팩터 (n>=10, {PRIMARY} mean 오름차순 — 저조한 순)")
    print("=" * 100)
    singles = []
    for lbl, _, axis in FACTORS:
        mask = apply_factor(df, lbl)
        stats = _all_stats(df, mask)
        if stats[PRIMARY]["n"] >= 10:
            singles.append((lbl, axis, stats))
    singles.sort(key=lambda x: (x[2][PRIMARY]["mean"] if x[2][PRIMARY]["mean"] is not None else 0.0))
    for lbl, axis, stats in singles:
        m = stats[PRIMARY]["mean"]
        marker = "▼" if m is not None and m < base_primary - 1 else " "
        line = "  ".join(f"{k.replace('alpha_','')}={stats[k]['mean']:+5.1f}%" if stats[k]["n"] else f"{k.replace('alpha_','')}=  —" for k in stats)
        print(f"  {marker} [{axis:6s}] {lbl:20s} n={stats[PRIMARY]['n']:4d}  {line}")
    _write_csv([_row(lbl, stats, axis) for lbl, axis, stats in singles], SINGLES_CSV)

    print()
    print("=" * 100)
    print(f"2. 2팩터 조합 (서로 다른 축, n>=20, {PRIMARY} base-2%p 이하)")
    print("=" * 100)
    labels = [f[0] for f in FACTORS]
    combos2 = []
    for a, b in combinations(labels, 2):
        if FACTOR_AXIS[a] == FACTOR_AXIS[b]:
            continue
        mask = apply_factor(df, a) & apply_factor(df, b)
        stats = _all_stats(df, mask)
        m = stats[PRIMARY]["mean"]
        if stats[PRIMARY]["n"] >= 20 and m is not None and m <= base_primary - 2:
            combos2.append((f"{a} + {b}", stats))
    combos2.sort(key=lambda x: x[1][PRIMARY]["mean"])
    for lbl, stats in combos2[:25]:
        line = "  ".join(f"{k.replace('alpha_','')}={stats[k]['mean']:+5.1f}%" if stats[k]["n"] else f"{k.replace('alpha_','')}=  —" for k in stats)
        print(f"  ▼ {lbl:40s} n={stats[PRIMARY]['n']:4d}  {line}")
    if not combos2:
        print("  (조건 만족 조합 없음)")
    else:
        print(f"  (총 {len(combos2)}개 중 상위 25개만 표시 — 전체는 CSV)")
    _write_csv([_row(lbl, stats) for lbl, stats in combos2], COMBO2_CSV)

    print()
    print("=" * 100)
    print(f"3. 3팩터 조합 (성장꺾임·투자압박·고평가 각 1개, n>=10, {PRIMARY} base-3%p 이하)")
    print("=" * 100)
    g_factors = [f[0] for f in FACTORS if f[2] == "성장꺾임"]
    i_factors = [f[0] for f in FACTORS if f[2] == "투자압박"]
    v_factors = [f[0] for f in FACTORS if f[2] == "고평가"]
    combos3 = []
    for g in g_factors:
        gm = apply_factor(df, g)
        if not gm.any():
            continue
        for i in i_factors:
            im = gm & apply_factor(df, i)
            if not im.any():
                continue
            for v in v_factors:
                mask = im & apply_factor(df, v)
                stats = _all_stats(df, mask)
                m = stats[PRIMARY]["mean"]
                if stats[PRIMARY]["n"] >= 10 and m is not None and m <= base_primary - 3:
                    combos3.append((f"{g} + {i} + {v}", stats))
    combos3.sort(key=lambda x: x[1][PRIMARY]["mean"])
    for lbl, stats in combos3[:20]:
        line = "  ".join(f"{k.replace('alpha_','')}={stats[k]['mean']:+5.1f}%" if stats[k]["n"] else f"{k.replace('alpha_','')}=  —" for k in stats)
        print(f"  ★ {lbl:55s} n={stats[PRIMARY]['n']:4d}  {line}")
    if not combos3:
        print("  (조건 만족 조합 없음 — n>=10 또는 base-3%p 조건 완화 필요)")
    else:
        print(f"  (총 {len(combos3)}개 중 상위 20개만 표시 — 전체는 CSV)")
    _write_csv([_row(lbl, stats) for lbl, stats in combos3], COMBO3_CSV)


if __name__ == "__main__":
    main()
