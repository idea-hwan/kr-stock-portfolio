"""
`ttm_valuation.db` 에서 롤4 주당 손익·현금흐름 컬럼 간 결측 불일치(이빨 빠짐) 점검.

기본: **수치 이빨**만 (매출 O·영업이익 X, CFO 원화 O·주당 X 등). `pl_dirty` 만 있는 종목은 제외.
  `--include-pl-dirty-only` 로 손익 차분 dirty 전부 포함 가능.

예:
  PYTHONPATH=. .venv/bin/python scripts/analysis/audit_ttm_pl_cf_gaps.py
  PYTHONPATH=. .venv/bin/python scripts/analysis/audit_ttm_pl_cf_gaps.py --anchor-term 2025Q4
  PYTHONPATH=. .venv/bin/python scripts/analysis/audit_ttm_pl_cf_gaps.py --exclude-financial-hint

앵커 행: `ttm_end_term` = `anchor_term` 인 행(스크립트 출력 [2][3] 의 마지막 줄과 동일 시점).
`series_error` 가 있는 행은 제외.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_DB = _ROOT / "data" / "analytics" / "ttm_valuation.db"

# 상장 CSV 에 업종이 없어 이름 힌트만 (금융 제외 필터용, 완전하지 않음)
_FIN_HINT_SUBSTR = (
    "은행",
    "증권",
    "투자증권",
    "보험",
    "생명",
    "손해보험",
    "금융지주",
    "금융",
    "캐피탈",
    "카드",
    "할부금융",
    "저축은행",
    "뱅크",
)


def _financial_name_hint(name: str) -> bool:
    n = str(name)
    return any(s in n for s in _FIN_HINT_SUBSTR)


def _has_val(v: object) -> bool:
    return v is not None and not (isinstance(v, float) and pd.isna(v))


def structural_pl_cf_gaps_dataframe(
    con: sqlite3.Connection,
    computed_at: str,
    anchor_term: str,
    *,
    include_pl_dirty_only: bool = False,
    exclude_financial_hint: bool = False,
) -> tuple[pd.DataFrame, int]:
    """
    앵커 행(ttm_end_term = anchor_term) 기준 PL/CF 롤4 구조적 결측(이빨) 목록.

    반환: (이슈가 있는 종목만 담은 DataFrame, 앵커 행이 있는 전체 종목 수)
    """
    sql = """
        SELECT
          company,
          ttm_end_term,
          rev_ps, op_ps, ni_parent_ps,
          cfo_ps, capex_ps, fcf_ps,
          ttm_cfo_krw, ttm_capex_krw, ttm_fcf_krw,
          pl_dirty
        FROM ttm_valuation_series
        WHERE computed_at = ?
          AND anchor_term = ?
          AND ttm_end_term = ?
          AND (series_error IS NULL OR series_error = '')
        """
    df = pd.read_sql_query(
        sql, con, params=(computed_at, anchor_term, anchor_term)
    )
    n_anchor = len(df)
    if df.empty:
        return pd.DataFrame(), 0

    flags: list[dict] = []
    for _, r in df.iterrows():
        co = str(r["company"])
        rev, op, ni = r["rev_ps"], r["op_ps"], r["ni_parent_ps"]
        cfo, capex, fcf = r["cfo_ps"], r["capex_ps"], r["fcf_ps"]
        kcfo, kcap, kfcf = r["ttm_cfo_krw"], r["ttm_capex_krw"], r["ttm_fcf_krw"]
        dirty_s = str(r["pl_dirty"]).strip() if _has_val(r["pl_dirty"]) else ""

        issues: list[str] = []
        if _has_val(rev) and not _has_val(ni):
            issues.append("rev_yes_ni_no")
        if _has_val(rev) and not _has_val(op):
            issues.append("rev_yes_op_no")
        if _has_val(op) and not _has_val(ni):
            issues.append("op_yes_ni_no")
        if _has_val(cfo) and not _has_val(fcf):
            issues.append("cfo_yes_fcf_no")
        if _has_val(cfo) and not _has_val(capex):
            issues.append("cfo_yes_capex_no")
        if _has_val(kcfo) and not _has_val(cfo):
            issues.append("krw_cfo_yes_ps_no")
        if _has_val(kcap) and not _has_val(capex):
            issues.append("krw_capex_yes_ps_no")
        if _has_val(kfcf) and not _has_val(fcf):
            issues.append("krw_fcf_yes_ps_no")
        structural = [x for x in issues if x != "pl_dirty"]
        if dirty_s:
            issues.append("pl_dirty")

        if not issues:
            continue
        if not structural and not include_pl_dirty_only:
            continue

        flags.append(
            {
                "company": co,
                "financial_hint": _financial_name_hint(co),
                "issues": ",".join(issues),
                "rev_ps": r["rev_ps"],
                "op_ps": r["op_ps"],
                "ni_parent_ps": r["ni_parent_ps"],
                "cfo_ps": r["cfo_ps"],
                "capex_ps": r["capex_ps"],
                "fcf_ps": r["fcf_ps"],
                "pl_dirty": dirty_s or None,
            }
        )

    out = pd.DataFrame(flags)
    if exclude_financial_hint and not out.empty:
        out = out.loc[~out["financial_hint"]].copy()
    return out, n_anchor


def _latest_batch(con: sqlite3.Connection) -> tuple[str, str]:
    row = con.execute(
        """
        SELECT computed_at, anchor_term
        FROM ttm_valuation_series
        GROUP BY computed_at, anchor_term
        ORDER BY computed_at DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        raise SystemExit("ttm_valuation_series 가 비어 있습니다.")
    return str(row[0]), str(row[1])


def main() -> int:
    p = argparse.ArgumentParser(description="TTM DB 손익·CF 롤4 결측 불일치 점검")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--computed-at", default=None, help="미지정 시 DB 최신 배치")
    p.add_argument("--anchor-term", default=None, help="미지정 시 최신 배치의 anchor")
    p.add_argument(
        "--exclude-financial-hint",
        action="store_true",
        help="이름에 은행·증권·보험·금융 등 힌트가 있으면 목록에서 제외",
    )
    p.add_argument(
        "--include-pl-dirty-only",
        action="store_true",
        help="손익 차분 dirty(pl_dirty)만 있고 수치 이빨은 없는 종목도 목록에 포함",
    )
    p.add_argument("--csv", type=Path, default=None)
    args = p.parse_args()

    if not args.db.is_file():
        print(f"DB 없음: {args.db}", file=sys.stderr)
        return 1

    con = sqlite3.connect(args.db)
    try:
        computed_at, anchor_term = (
            (args.computed_at, args.anchor_term)
            if args.computed_at and args.anchor_term
            else _latest_batch(con)
        )
        if args.computed_at:
            computed_at = args.computed_at
        if args.anchor_term:
            anchor_term = args.anchor_term

        out, n_anchor = structural_pl_cf_gaps_dataframe(
            con,
            computed_at,
            anchor_term,
            include_pl_dirty_only=args.include_pl_dirty_only,
            exclude_financial_hint=args.exclude_financial_hint,
        )
    finally:
        con.close()

    if n_anchor == 0:
        print(
            f"조건에 맞는 행 없음: computed_at={computed_at} anchor={anchor_term}",
            file=sys.stderr,
        )
        return 2

    print(
        f"batch computed_at={computed_at}  anchor={anchor_term}  "
        f"앵커 행 기준 종목 수: {n_anchor}  이슈 종목: {len(out)}"
    )
    if out.empty:
        print("(조건에 해당하는 불일치 없음)")
        return 0

    show = out.drop(columns=["financial_hint"], errors="ignore")
    with pd.option_context("display.max_rows", 200, "display.width", 200):
        print(show.to_string(index=False))

    if args.csv:
        out.to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"\nCSV: {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
