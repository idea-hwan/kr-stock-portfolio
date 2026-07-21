"""
§3.3 대형 성장주 스모크: 시총 상위 200 × ttm_valuation 만 사용.
  분기 이력이 min-q(기본 16)개 이상이고, 시계열 끝에서 min-q개 분기 각각 op_ps > 0.
  (동일 anchor_term=as_of, 종목별 최신 computed_at 배치 안에서 ttm_end_term ≤ as_of 만 사용.)

  §3.2 대형 밸류주(ni_parent_ps 기준)와 대칭 구조 — 순이익 대신 영업이익만 다르다.
  성장가속(op 2y CAGR > 4y CAGR) 조건은 버킷 분류에 안 쓴다 — 매수신호 단계
  (`docs/large_growth_selection_strategy.md` Signal B)로 옮겨졌다(us-stock-portfolio의
  현재 classify_stocks.py/pit_buckets16과 동일한 구조: growth·value 모두 순수 흑자
  스트릭 단독 조건, 비배타적).

  .venv/bin/python scripts/analysis/screen_large_growth_mcap200.py
  .venv/bin/python scripts/analysis/screen_large_growth_mcap200.py --as-of 2026Q1 --list-pass
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

from scripts.analysis.screen_large_asset_mcap200 import _snapshot_by_company, _val_n_terms
from scripts.config import PROFIT_STREAK_MIN_Q

MCAP_CSV = _ROOT / "stock_data" / "mcap_top_200.csv"
VAL_DB = _ROOT / "data" / "analytics" / "ttm_valuation.db"


def _default_as_of(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(ttm_end_term) FROM ttm_valuation_series").fetchone()
    return str(row[0]) if row and row[0] else None


def _last_n_quarters_op_ps_positive(
    conn: sqlite3.Connection,
    company: str,
    anchor: str,
    computed_at: str,
    as_of: str,
    min_q: int,
) -> bool:
    """
    ttm_end_term ≤ as_of 분기만 모음 → 정렬 후 **마지막 min_q개 분기**마다 op_ps > 0.
    전체 이력이 min_q 미만이면 실패. 동일 분기 중복 행은 마지막 행 기준.
    """
    rows = conn.execute(
        """
        SELECT ttm_end_term, op_ps
        FROM ttm_valuation_series
        WHERE company = ? AND anchor_term = ? AND computed_at = ? AND ttm_end_term <= ?
        ORDER BY ttm_end_term
        """,
        (company, anchor, computed_at, as_of),
    ).fetchall()
    by_term: dict[str, object] = {}
    for t, op in rows:
        by_term[str(t)] = op
    terms_sorted = sorted(by_term.keys())
    if len(terms_sorted) < min_q:
        return False
    for term in terms_sorted[-min_q:]:
        op = by_term[term]
        if op is None or float(op) <= 0:
            return False
    return True


def large_growth_passing_names(
    *,
    as_of: str | None = None,
    min_q: int = PROFIT_STREAK_MIN_Q,
    mcap_csv: Path = MCAP_CSV,
    val_db: Path = VAL_DB,
) -> tuple[str, list[str]]:
    """
    §3.3 스모크 통과 종목명 (mcap_top_200 파일 순서).
    반환: (as_of, names).
    """
    if not mcap_csv.is_file():
        raise FileNotFoundError(mcap_csv)
    if not val_db.is_file():
        raise FileNotFoundError(val_db)
    mcap = pd.read_csv(mcap_csv, dtype={"Code": str})
    names = [str(x).strip() for x in mcap["Name"].tolist()]
    vconn = sqlite3.connect(val_db)
    as_res = as_of or _default_as_of(vconn)
    if not as_res:
        vconn.close()
        raise RuntimeError("as_of 를 정할 수 없습니다 (ttm_valuation_series 비었을 수 있음).")
    snap = _snapshot_by_company(vconn, as_res)
    passed: list[str] = []
    for n in names:
        if n not in snap:
            continue
        ct, _ = snap[n]
        if not _last_n_quarters_op_ps_positive(vconn, n, as_res, ct, as_res, min_q):
            continue
        passed.append(n)
    vconn.close()
    return as_res, passed


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", type=str, default=None)
    p.add_argument(
        "--min-q",
        type=int,
        default=PROFIT_STREAK_MIN_Q,
        help=f"시계열 끝에서 N개 분기 각각 op_ps > 0; N 기본 {PROFIT_STREAK_MIN_Q}",
    )
    p.add_argument("--list-pass", action="store_true")
    args = p.parse_args()

    try:
        as_of, passed = large_growth_passing_names(
            as_of=args.as_of, min_q=args.min_q, mcap_csv=MCAP_CSV, val_db=VAL_DB
        )
    except FileNotFoundError as e:
        print(f"Missing {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    mcap = pd.read_csv(MCAP_CSV, dtype={"Code": str})
    names = [str(x).strip() for x in mcap["Name"].tolist()]
    if len(names) != 200:
        print(f"Warning: mcap CSV has {len(names)} rows (expected 200)", file=sys.stderr)

    vconn = sqlite3.connect(VAL_DB)
    snap = _snapshot_by_company(vconn, as_of)
    n_snap = sum(1 for n in names if n in snap)
    n_anchor = 0
    for n in names:
        if n not in snap:
            continue
        ct, _ = snap[n]
        if _val_n_terms(vconn, n, as_of, ct, as_of) >= args.min_q:
            n_anchor += 1
    vconn.close()

    print(f"as_of={as_of}  source=ttm_valuation.db only")
    print(f"mcap names: {len(names)}")
    print(f"snapshot row (anchor=ttm_end={as_of}, latest computed_at): {n_snap}")
    print(f"DISTINCT terms <= as_of >= {args.min_q} (same anchor·computed_at): {n_anchor}")
    print(f"PASS (≥{args.min_q} terms, last {args.min_q} consecutive: op_ps > 0 each): {len(passed)}")
    if args.list_pass:
        for n in passed:
            print(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
