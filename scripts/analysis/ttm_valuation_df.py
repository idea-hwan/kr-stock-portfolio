"""
`data/analytics/ttm_valuation.db` 의 `ttm_valuation_series` 를 종목별 DataFrame 으로 조회.

예:
  python scripts/analysis/ttm_valuation_df.py --company 삼성전자
  python scripts/analysis/ttm_valuation_df.py -n 30
  python scripts/analysis/ttm_valuation_df.py --company 삼성전자 --view wide
  python scripts/analysis/ttm_valuation_df.py --company 삼성전자 --view transpose --term 2025Q4
  python scripts/analysis/ttm_valuation_df.py --company 삼성전자 --csv /tmp/sam.csv
  python scripts/analysis/ttm_valuation_df.py --top-n 30 --anchor-term 2025Q4 --tail 5

노트북에서:
  from scripts.analysis.ttm_valuation_df import load_ttm_valuation_df
  df = load_ttm_valuation_df("삼성전자")
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.stock_db import listing_names_ordered_by_marcap

DEFAULT_DB = _ROOT / "data" / "analytics" / "ttm_valuation.db"

pd.set_option("display.max_rows", 200)
pd.set_option("display.max_columns", 30)
pd.set_option("display.width", 120)
pd.set_option("display.unicode.east_asian_width", True)

_DISPLAY_COLS = [
    "ttm_end_term",
    "window_terms",
    "series_error",
    "rev_ps",
    "op_ps",
    "ni_parent_ps",
    "fy_rev_ps",
    "fy_op_ps",
    "fy_ni_ps",
    "income_source",
    "cfo_ps",
    "capex_ps",
    "fcf_ps",
    "ttm_cfo_krw",
    "ttm_capex_krw",
    "ttm_fcf_krw",
    "face_value_end",
    "istc_ffill_end",
    "pl_dirty",
    "per_filing_anchor",
    "per_anchor_trade_date",
    "per_anchor_close",
    "per_eps_adjusted",
    "per_20d_mean",
    "per_4y_mean",
    "per_op_20d_mean",
    "per_op_4y_mean",
    "per_rev_20d_mean",
    "per_rev_4y_mean",
    "per_fcf_20d_mean",
    "per_fcf_4y_mean",
    "per_run_error",
    "computed_at",
    "anchor_term",
    "logic_version",
]

# (section title, columns including ttm_end_term for join readability)
_SPLIT_GROUPS: list[tuple[str, list[str]]] = [
    (
        "[1] core",
        [
            "ttm_end_term",
            "series_error",
            "income_source",
            "pl_dirty",
            "window_terms",
        ],
    ),
    (
        "[2] P/L per share (roll4 + FY)",
        [
            "ttm_end_term",
            "rev_ps",
            "op_ps",
            "ni_parent_ps",
            "fy_rev_ps",
            "fy_op_ps",
            "fy_ni_ps",
        ],
    ),
    (
        "[3] cash flow per share + TTM sum (KRW)",
        [
            "ttm_end_term",
            "cfo_ps",
            "capex_ps",
            "fcf_ps",
            "ttm_cfo_krw",
            "ttm_capex_krw",
            "ttm_fcf_krw",
        ],
    ),
    (
        "[4] scale",
        ["ttm_end_term", "face_value_end", "istc_ffill_end"],
    ),
    (
        "[5a] Valuation anchor (filing date → trade day close, adj. EPS)",
        [
            "ttm_end_term",
            "per_filing_anchor",
            "per_anchor_trade_date",
            "per_anchor_close",
            "per_eps_adjusted",
            "per_run_error",
        ],
    ),
    (
        "[5b] PER = P ÷ TTM NI/sh (20d mean close, 4y mean daily ratio)",
        ["ttm_end_term", "per_20d_mean", "per_4y_mean"],
    ),
    (
        "[5c] P ÷ TTM operating income / sh",
        ["ttm_end_term", "per_op_20d_mean", "per_op_4y_mean"],
    ),
    (
        "[5d] P ÷ TTM revenue / sh",
        ["ttm_end_term", "per_rev_20d_mean", "per_rev_4y_mean"],
    ),
    (
        "[5e] P ÷ TTM FCF / sh (FY 우선폴백 없음, roll4만)",
        ["ttm_end_term", "per_fcf_20d_mean", "per_fcf_4y_mean"],
    ),
]


def _is_na(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return True
    try:
        return bool(pd.isna(v))
    except (ValueError, TypeError):
        return False


def _fmt_cell(col: str, v: Any) -> str:
    if _is_na(v):
        return "—"
    if col == "window_terms":
        s = str(v).strip()
        if not s:
            return "—"
        try:
            arr = json.loads(s)
            if isinstance(arr, list) and len(arr) > 6:
                return json.dumps([arr[0], "…", arr[-1]], ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass
        return s if len(s) <= 44 else s[:41] + "…"
    if col == "pl_dirty":
        s = str(v).strip()
        return s if len(s) <= 48 else s[:45] + "…"
    if col in ("ttm_cfo_krw", "ttm_capex_krw", "ttm_fcf_krw"):
        try:
            return f"{int(round(float(v))):,}"
        except (TypeError, ValueError):
            return str(v)
    if col.endswith("_ps") or (
        col.startswith("per_")
        and col
        not in (
            "per_filing_anchor",
            "per_anchor_trade_date",
            "per_anchor_close",
            "per_run_error",
        )
    ):
        try:
            return f"{float(v):,.2f}"
        except (TypeError, ValueError):
            return str(v)
    if col == "per_anchor_close":
        try:
            return f"{float(v):,.0f}"
        except (TypeError, ValueError):
            return str(v)
    if col == "face_value_end":
        try:
            return f"{float(v):,.0f}"
        except (TypeError, ValueError):
            return str(v)
    if col == "istc_ffill_end":
        try:
            return f"{float(v) / 1_000_000.0:,.2f}M"
        except (TypeError, ValueError):
            return str(v)
    s = str(v).strip()
    return s if s else "—"


def dataframe_as_display_strings(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for c in df.columns:
        out[c] = df[c].map(lambda x, col=c: _fmt_cell(col, x))
    return out


def print_meta_line(df: pd.DataFrame) -> None:
    if df.empty:
        return
    row = df.iloc[0]
    co = row["company"] if "company" in df.columns else "—"
    ca = row["computed_at"] if "computed_at" in df.columns else "—"
    an = row["anchor_term"] if "anchor_term" in df.columns else "—"
    lv = row["logic_version"] if "logic_version" in df.columns else "—"
    print(f"company={co}  batch={ca}  anchor={an}  logic={lv}  rows={len(df)}")


def print_split_view(df: pd.DataFrame) -> None:
    print_meta_line(df)
    print()
    for title, cols in _SPLIT_GROUPS:
        use = [c for c in cols if c in df.columns]
        if len(use) <= 1:
            continue
        sub = df.loc[:, use].copy()
        disp = dataframe_as_display_strings(sub)
        print(title)
        with pd.option_context("display.max_colwidth", 50, "display.width", 200):
            print(disp.to_string(index=False))
        print()


def print_wide_view(df: pd.DataFrame) -> None:
    print_meta_line(df)
    print()
    disp = dataframe_as_display_strings(df)
    meta_cols = {"computed_at", "anchor_term", "logic_version", "company"}
    front = [c for c in disp.columns if c not in meta_cols]
    back = [c for c in disp.columns if c in meta_cols]
    disp = disp[front + back]
    with pd.option_context("display.max_columns", None, "display.width", 240):
        print(disp.to_string(index=False))


def print_transpose_view(df: pd.DataFrame, term: str | None) -> None:
    print_meta_line(df)
    print()
    if term:
        m = df.loc[df["ttm_end_term"].astype(str) == term]
        if m.empty:
            print(f"no row for ttm_end_term={term}", file=sys.stderr)
            return
        row = m.iloc[-1]
    else:
        row = df.iloc[-1]
    te = row.get("ttm_end_term", "")
    print(f"--- snapshot ttm_end_term={te} ---\n")
    ser = row.drop(labels=["id"], errors="ignore")
    disp = pd.Series({k: _fmt_cell(k, ser[k]) for k in ser.index})
    # column order: logical blocks
    print(disp.to_string())


def load_ttm_valuation_df(
    company: str,
    *,
    db_path: Path | None = None,
    anchor_term: str | None = None,
    computed_at: str | None = None,
) -> pd.DataFrame:
    """
    한 종목의 시계열 행을 시간순(ttm_end_term)으로 반환.
    `computed_at` 생략 시 해당 종목에 대해 DB에 있는 가장 최근 배치만 사용.
    """
    path = Path(db_path) if db_path else DEFAULT_DB
    if not path.is_file():
        raise FileNotFoundError(f"DB 없음: {path}")

    con = sqlite3.connect(path)
    try:
        params: list = [company]
        where = "company = ?"
        if anchor_term:
            where += " AND anchor_term = ?"
            params.append(anchor_term)
        if computed_at:
            where += " AND computed_at = ?"
            params.append(computed_at)
        else:
            sub = "SELECT MAX(computed_at) FROM ttm_valuation_series WHERE company = ?"
            sub_params: list = [company]
            if anchor_term:
                sub += " AND anchor_term = ?"
                sub_params.append(anchor_term)
            cur = con.execute(sub, sub_params)
            row = cur.fetchone()
            latest = row[0] if row else None
            if latest is None:
                return pd.DataFrame()
            where += " AND computed_at = ?"
            params.append(latest)

        sql = f"SELECT * FROM ttm_valuation_series WHERE {where} ORDER BY ttm_end_term ASC"
        df = pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()

    if df.empty:
        return df

    ordered = [c for c in _DISPLAY_COLS if c in df.columns]
    rest = [c for c in df.columns if c not in ordered and c != "id"]
    df = df[ordered + rest]
    return df


def main() -> int:
    p = argparse.ArgumentParser(
        description="ttm_valuation.db → 종목별 조회 (기본: 주제별 좁은 표)",
        epilog=(
            "예: python scripts/analysis/ttm_valuation_df.py --company 삼성전자\n"
            "예: python scripts/analysis/ttm_valuation_df.py -n 30   (--n 30 / --top-n 30 동일)\n"
            "※ .py 는 chmod +x 하지 않았다면 직접 실행하지 말고 앞에 python 을 붙인다."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument(
        "--company",
        default=None,
        help="종목명 (stock_listing Name 과 동일)",
    )
    sel.add_argument(
        "-n",
        "--top-n",
        "--n",
        type=int,
        default=None,
        dest="top_n",
        metavar="N",
        help="시총(Marcap) 상위 N개 — stock_listing.csv 순서 (-n / --n / --top-n 동일)",
    )
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 경로")
    p.add_argument("--anchor-term", default=None, help="예: 2025Q4")
    p.add_argument("--computed-at", default=None, help="특정 배치만 (기본: 최신)")
    p.add_argument(
        "--view",
        choices=("split", "wide", "transpose"),
        default="split",
        help="split=주제별 표(기본, 가격배수는 [5a]~[5d]로 분할), wide=전열 한 번, transpose=한 분기 세로",
    )
    p.add_argument(
        "--term",
        default=None,
        help="transpose 시 해당 ttm_end_term (미지정이면 마지막 행)",
    )
    p.add_argument("--csv", type=Path, default=None, help="저장 시 CSV 경로")
    p.add_argument("--tail", type=int, default=None, help="출력 전 마지막 N행만 사용")
    args = p.parse_args()

    view_eff = args.view
    if args.top_n is not None and args.view == "transpose" and args.top_n > 1:
        view_eff = "split"
        print(
            "(--top-n > 1 이므로 transpose 대신 split 로 출력합니다.)",
            file=sys.stderr,
        )

    if args.top_n is not None:
        if args.top_n < 1:
            print("에러: -n / --top-n 은 1 이상이어야 합니다.", file=sys.stderr)
            return 1
        names = listing_names_ordered_by_marcap(market=None)[: args.top_n]
        dfs: list[pd.DataFrame] = []
        n_ok = 0
        for i, co in enumerate(names, start=1):
            try:
                df = load_ttm_valuation_df(
                    co,
                    db_path=args.db,
                    anchor_term=args.anchor_term,
                    computed_at=args.computed_at,
                )
            except FileNotFoundError as e:
                print(e, file=sys.stderr)
                return 1
            if df.empty:
                print(
                    f"======== [{i}/{len(names)}] {co} — ttm_valuation.db 에 행 없음 ==========\n"
                )
                continue
            n_ok += 1
            if args.tail is not None:
                df = df.tail(args.tail)
            print(f"======== [{i}/{len(names)}] {co} ==========\n")
            if view_eff == "wide":
                print_wide_view(df)
            else:
                print_split_view(df)
            print()
            dfs.append(df)
        if args.csv:
            if dfs:
                pd.concat(dfs, ignore_index=True).to_csv(
                    args.csv, index=False, encoding="utf-8-sig"
                )
                print(f"CSV ({len(dfs)} 종목 합본): {args.csv}")
            else:
                print("CSV 생략: 적재된 종목이 없습니다.", file=sys.stderr)
        return 0 if n_ok else 2

    try:
        df = load_ttm_valuation_df(
            args.company,
            db_path=args.db,
            anchor_term=args.anchor_term,
            computed_at=args.computed_at,
        )
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    if df.empty:
        print(
            f"'{args.company}' 데이터 없음 (조건: anchor={args.anchor_term}, computed_at={args.computed_at})"
        )
        return 2

    if args.tail is not None:
        df = df.tail(args.tail)

    if args.view == "wide":
        print_wide_view(df)
    elif args.view == "transpose":
        print_transpose_view(df, args.term)
    else:
        print_split_view(df)

    print(f"[printed rows={len(df)}  cols={len(df.columns)}]")

    if args.csv:
        df.to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"CSV: {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
