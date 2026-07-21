"""
대형 밸류주 렌즈: 분기별 밸류·주당 원천 + 성장률(1·2·4년, op/ni/cfo/fcf).

  기본: 분기별 표(stdout). 경기순환 POC와 동일한 signal1(싸다) 정의를 분기마다 계산 가능.

  싸다(signal1): per_op_20d/per_op_4y < 1 AND per_rev_20d/per_rev_4y < 1
  성장률: ttm_metric_growth 의 *_geom_{1y,2y,4y}_mcum (op, ni, cfo, fcf)

  예:
    .venv/bin/python scripts/analysis/large_asset_lens_snapshot.py --company 현대차
    .venv/bin/python scripts/analysis/large_asset_lens_snapshot.py --company 현대차 --as-of 2025Q4
    .venv/bin/python scripts/analysis/large_asset_lens_snapshot.py --company 현대차 --wide   # 가로 한 덩어리(복붙용)
    .venv/bin/python scripts/analysis/large_asset_lens_snapshot.py --company 현대차 --summary
    .venv/bin/python scripts/analysis/large_asset_lens_snapshot.py --company 현대차 --csv /tmp/hyundai.csv
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis.ttm_valuation_df import load_ttm_valuation_df
from scripts.screening.ttm_metric_growth import build_ttm_metric_growth_df

VAL_DB = _ROOT / "data" / "analytics" / "ttm_valuation.db"

_VAL_COLS = [
    "ttm_end_term",
    "op_ps",
    "ni_parent_ps",
    "cfo_ps",
    "fcf_ps",
    "per_op_20d_mean",
    "per_op_4y_mean",
    "per_rev_20d_mean",
    "per_rev_4y_mean",
    "per_20d_mean",
    "per_4y_mean",
]

_GROWTH_PREFIXES = ("op", "ni", "cfo", "fcf")
_GROWTH_HORIZONS = ("1y", "2y", "4y")


def _ratio_lt_1(a: float | None, b: float | None) -> bool | None:
    if a is None or b is None:
        return None
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(fa) or not np.isfinite(fb) or fb <= 0:
        return None
    return (fa / fb) < 1.0


def _signal1_row(row: pd.Series) -> float:
    r_op = _ratio_lt_1(row.get("per_op_20d_mean"), row.get("per_op_4y_mean"))
    r_rev = _ratio_lt_1(row.get("per_rev_20d_mean"), row.get("per_rev_4y_mean"))
    if r_op is None or r_rev is None:
        return float("nan")
    return float(int(r_op and r_rev))


def _is_bad_num(v: object) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    try:
        x = float(v)
    except (TypeError, ValueError):
        return True
    return not np.isfinite(x)


def _fmt_ps(v: object) -> str:
    if _is_bad_num(v):
        return "—"
    return f"{float(v):,.0f}"


def _fmt_per(v: object) -> str:
    if _is_bad_num(v):
        return "—"
    return f"{float(v):.2f}"


def _fmt_pct(v: object) -> str:
    if _is_bad_num(v):
        return "—"
    return f"{float(v):+.2f}"


def _fmt_s1(v: object) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    try:
        if pd.isna(v):
            return "—"
    except (TypeError, ValueError):
        pass
    return str(int(v))


def _print_section(title: str, df: pd.DataFrame, term_w: int) -> None:
    bar = "─" * min(72, max(40, term_w - 4))
    print(f"\n{bar}\n  {title}\n{bar}")
    with pd.option_context(
        "display.unicode.east_asian_width",
        True,
        "display.max_rows",
        200,
        "display.width",
        term_w,
        "display.max_columns",
        None,
        "display.max_colwidth",
        14,
    ):
        print(df.to_string(index=False))


def _print_readable_quarterly(out: pd.DataFrame) -> None:
    term_w = max(100, min(140, shutil.get_terminal_size(fallback=(120, 24)).columns))

    term = out["ttm_end_term"].astype(str)
    n = len(out)
    dash = pd.Series(["—"] * n)

    def col(name: str, fn) -> pd.Series:
        if name not in out.columns:
            return dash.copy()
        return out[name].map(fn)

    b1 = pd.DataFrame(
        {
            "분기": term,
            "영업/ps": col("op_ps", _fmt_ps),
            "지배순/ps": col("ni_parent_ps", _fmt_ps),
            "CFO/ps": col("cfo_ps", _fmt_ps),
            "FCF/ps": col("fcf_ps", _fmt_ps),
        }
    )
    _print_section("[1] TTM 주당 (원/주)", b1, term_w)

    b2 = pd.DataFrame(
        {
            "분기": term,
            "P/영업_20d": col("per_op_20d_mean", _fmt_per),
            "P/영업_4y": col("per_op_4y_mean", _fmt_per),
            "P/매출_20d": col("per_rev_20d_mean", _fmt_per),
            "P/매출_4y": col("per_rev_4y_mean", _fmt_per),
            "PER_20d": col("per_20d_mean", _fmt_per),
            "PER_4y": col("per_4y_mean", _fmt_per),
            "s1": col("signal1_cheap", _fmt_s1),
        }
    )
    _print_section("[2] 배수 · signal1 (s1=1 싸다, P/영업·P/매출 20d/4y 각각 <1)", b2, term_w)

    def _g(pref: str) -> tuple[pd.Series, pd.Series, pd.Series]:
        a = f"{pref}_geom_1y_mcum"
        b = f"{pref}_geom_2y_mcum"
        c = f"{pref}_geom_4y_mcum"
        return (col(a, _fmt_pct), col(b, _fmt_pct), col(c, _fmt_pct))

    op1, op2, op4 = _g("op")
    ni1, ni2, ni4 = _g("ni")
    b3 = pd.DataFrame(
        {
            "분기": term,
            "영업_1y%": op1,
            "영업_2y%": op2,
            "영업_4y%": op4,
            "지배순_1y%": ni1,
            "지배순_2y%": ni2,
            "지배순_4y%": ni4,
        }
    )
    _print_section("[3] 성장률 % (기하 누적, geom_*_mcum) — 영업 · 지배순", b3, term_w)

    c1, c2, c4 = _g("cfo")
    f1, f2, f4 = _g("fcf")
    b4 = pd.DataFrame(
        {
            "분기": term,
            "CFO_1y%": c1,
            "CFO_2y%": c2,
            "CFO_4y%": c4,
            "FCF_1y%": f1,
            "FCF_2y%": f2,
            "FCF_4y%": f4,
        }
    )
    _print_section("[4] 성장률 % — CFO · FCF", b4, term_w)


def _growth_column_names(df: pd.DataFrame) -> list[str]:
    names: list[str] = []
    for pref in _GROWTH_PREFIXES:
        for h in _GROWTH_HORIZONS:
            c = f"{pref}_geom_{h}_mcum"
            if c in df.columns:
                names.append(c)
    return names


def _load_valuation_row(company: str, as_of: str) -> pd.Series | None:
    con = sqlite3.connect(VAL_DB)
    try:
        rows = con.execute(
            """
            SELECT * FROM ttm_valuation_series
            WHERE company = ? AND anchor_term = ? AND ttm_end_term = ?
            ORDER BY computed_at DESC
            LIMIT 1
            """,
            (company, as_of, as_of),
        ).fetchall()
        cols = [d[1] for d in con.execute("PRAGMA table_info(ttm_valuation_series)").fetchall()]
    finally:
        con.close()
    if not rows:
        return None
    return pd.Series(dict(zip(cols, rows[0])))


def _default_as_of() -> str | None:
    con = sqlite3.connect(VAL_DB)
    try:
        r = con.execute("SELECT MAX(ttm_end_term) FROM ttm_valuation_series").fetchone()
    finally:
        con.close()
    return str(r[0]) if r and r[0] else None


def _build_quarterly_table(company: str, as_of: str) -> tuple[pd.DataFrame, str | None]:
    """병합 표 + 최신 배치 computed_at (첫 행)."""
    val = load_ttm_valuation_df(company, db_path=VAL_DB, anchor_term=as_of)
    if val.empty:
        return pd.DataFrame(), None

    g = build_ttm_metric_growth_df(company, db_path=VAL_DB, anchor_term=as_of)
    if g.empty:
        return pd.DataFrame(), None

    vcols = [c for c in _VAL_COLS if c in val.columns]
    base = val[vcols].copy()

    gcols = ["ttm_end_term"] + _growth_column_names(g)
    gsub = g[[c for c in gcols if c in g.columns]].copy()

    out = base.merge(gsub, on="ttm_end_term", how="left")
    s1 = out.apply(_signal1_row, axis=1)
    out["signal1_cheap"] = pd.array(
        [pd.NA if (isinstance(x, float) and np.isnan(x)) else int(x) for x in s1],
        dtype="Int64",
    )

    # 열 순서: 분기 → 주당 → 배수 → signal1 → 성장( op 1y2y4y, ni … )
    front = [c for c in _VAL_COLS if c in out.columns]
    mid = ["signal1_cheap"] if "signal1_cheap" in out.columns else []
    grow_names = _growth_column_names(out)
    ordered = front + mid + [c for c in grow_names if c in out.columns]
    out = out[[c for c in ordered if c in out.columns]]

    ct = val.iloc[0].get("computed_at") if len(val) else None
    return out, str(ct) if ct is not None else None


def _print_summary(company: str, as_of: str) -> int:
    v = _load_valuation_row(company, as_of)
    if v is None:
        print(f"{company!r} × as_of={as_of} 스냅샷 행 없음", file=sys.stderr)
        return 1

    g = build_ttm_metric_growth_df(company, db_path=VAL_DB, anchor_term=as_of)
    if g.empty:
        print("성장 시계열 비어 있음", file=sys.stderr)
        return 1
    gr = g[g["ttm_end_term"] == as_of]
    if gr.empty:
        gr = g.tail(1)
        te = str(gr.iloc[0]["ttm_end_term"])
        print(f"주의: as_of={as_of} 성장 행 없음 → 최신 분기 {te} 사용", file=sys.stderr)
    grow = gr.iloc[0]

    r_op = _ratio_lt_1(v.get("per_op_20d_mean"), v.get("per_op_4y_mean"))
    r_rev = _ratio_lt_1(v.get("per_rev_20d_mean"), v.get("per_rev_4y_mean"))
    r_ni = _ratio_lt_1(v.get("per_20d_mean"), v.get("per_4y_mean"))
    s1_cyclical = (r_op and r_rev) if r_op is not None and r_rev is not None else None

    print(f"company={company}  as_of={as_of}  computed_at={v.get('computed_at')}")
    print()
    print("[싸다 — 경기순환 POC signal1 동일: op·매출 배수]")
    print(
        f"  per_op_20d={v.get('per_op_20d_mean')!s}  per_op_4y={v.get('per_op_4y_mean')!s}  "
        f"20d/4y<1 → {r_op}"
    )
    print(
        f"  per_rev_20d={v.get('per_rev_20d_mean')!s}  per_rev_4y={v.get('per_rev_4y_mean')!s}  "
        f"20d/4y<1 → {r_rev}"
    )
    print(f"  signal1 (둘 다): {s1_cyclical}")
    print()
    print("[보조 — 지배순 PER]")
    print(
        f"  per_20d={v.get('per_20d_mean')!s}  per_4y={v.get('per_4y_mean')!s}  "
        f"20d/4y<1 → {r_ni}"
    )
    print()
    print("[TTM 주당 원천 — 스냅샷]")
    for k in ("op_ps", "ni_parent_ps", "cfo_ps", "fcf_ps"):
        print(f"  {k}: {v.get(k)!s}")
    print()
    print("[성장률 % — geom_*_mcum, 분기={}]".format(grow["ttm_end_term"]))
    for pref in _GROWTH_PREFIXES:
        for h in _GROWTH_HORIZONS:
            k = f"{pref}_geom_{h}_mcum"
            if k not in grow.index:
                continue
            val = grow.get(k)
            disp = "—" if val is None or (isinstance(val, float) and np.isnan(val)) else f"{float(val):.4f}"
            print(f"  {k}: {disp}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="대형 밸류주 렌즈 — 분기별 표 기본(섹션·포맷), --wide 원시 표, --summary 스냅샷"
    )
    p.add_argument("--company", type=str, required=True)
    p.add_argument("--as-of", type=str, default=None, help="anchor_term·기준 분기 (기본: DB MAX(ttm_end_term))")
    p.add_argument(
        "--summary",
        action="store_true",
        help="as_of 스냅샷 한 줄 요약만 (이전 동작)",
    )
    p.add_argument("--csv", type=Path, default=None, help="분기별 표를 CSV로 저장")
    p.add_argument(
        "--wide",
        action="store_true",
        help="가로 한 줄짜리 넓은 표(원시 컬럼명, 복붙·파이프용). 기본은 섹션별 가독성 출력",
    )
    args = p.parse_args()

    if not VAL_DB.is_file():
        print(f"Missing {VAL_DB}", file=sys.stderr)
        return 1

    company = args.company.strip()
    as_of = args.as_of or _default_as_of()
    if not as_of:
        print("as_of 를 정할 수 없습니다.", file=sys.stderr)
        return 1

    if args.summary:
        return _print_summary(company, as_of)

    out, computed_at = _build_quarterly_table(company, as_of)
    if out.empty:
        print(
            f"{company!r} 분기별 병합 실패 (valuation 또는 growth 비어 있음), as_of={as_of}",
            file=sys.stderr,
        )
        return 1

    meta = f"company={company}  anchor_term={as_of}  valuation_computed_at={computed_at}"
    print(meta)
    print(f"rows={len(out)}  (넓은 한 표: --wide)")

    if args.wide:
        disp = out.copy()
        if "signal1_cheap" in disp.columns:
            disp["signal1_cheap"] = [
                "—" if pd.isna(x) else str(int(x)) for x in out["signal1_cheap"]
            ]
        tw = max(120, shutil.get_terminal_size(fallback=(160, 24)).columns)
        with pd.option_context(
            "display.max_rows",
            200,
            "display.width",
            tw,
            "display.max_columns",
            None,
        ):
            print()
            print(disp.to_string(index=False, na_rep="—", float_format=lambda x: f"{x:.4f}"))
    else:
        _print_readable_quarterly(out)

    if args.csv is not None:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(args.csv, index=False)
        print(f"\nWrote {args.csv}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
