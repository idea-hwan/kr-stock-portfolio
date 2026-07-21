"""
§3.3 대형 성장주 스모크: mcap_top_200 × ttm_metric_growth.db + ttm_valuation.db
  1) 시총 상위 200
  2) growth: 행 수 최대 batch_label, as_of 이하 DISTINCT ttm_end_term >= min-q(기본 28)
  3) valuation: 동일 anchor_term=as_of·종목별 최신 computed_at 배치에서 최근 min-q분기 연속 op_ps > 0
  4) growth as_of 행: op_geom_1y/2y/4y 비결측이고 1y>0, 2y>0, 4y>0, 2y>4y

  (§2 경기순환·자산 선배정 제외.)

  .venv/bin/python scripts/analysis/screen_large_growth_mcap200.py
  .venv/bin/python scripts/analysis/screen_large_growth_mcap200.py --list-pass
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis.screen_large_asset_mcap200 import _snapshot_by_company

MCAP_CSV = _ROOT / "stock_data" / "mcap_top_200.csv"
GROWTH_DB = _ROOT / "data" / "analytics" / "ttm_metric_growth.db"
VAL_DB = _ROOT / "data" / "analytics" / "ttm_valuation.db"


def _is_null(x: object) -> bool:
    if x is None:
        return True
    if isinstance(x, float) and math.isnan(x):
        return True
    return False


def _main_batch(conn: sqlite3.Connection) -> str:
    # 최신 분기가 포함된 배치 우선 (행 수만 보면 구 배치가 이길 수 있음)
    row = conn.execute(
        """
        SELECT batch_label FROM ttm_metric_growth_series
        GROUP BY batch_label
        ORDER BY MAX(ttm_end_term) DESC, COUNT(*) DESC
        LIMIT 1
        """
    ).fetchone()
    if not row or not row[0]:
        raise RuntimeError("ttm_metric_growth_series 가 비었거나 batch_label 이 없습니다.")
    return str(row[0])


def _default_as_of_growth(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(ttm_end_term) FROM ttm_metric_growth_series").fetchone()
    return str(row[0]) if row and row[0] else None


def _growth_n_terms(conn: sqlite3.Connection, batch: str, as_of: str) -> dict[str, int]:
    q = """
    SELECT company, COUNT(DISTINCT ttm_end_term) AS n
    FROM ttm_metric_growth_series
    WHERE batch_label = ? AND ttm_end_term <= ?
    GROUP BY company
    """
    return {str(r[0]): int(r[1]) for r in conn.execute(q, (batch, as_of))}


def _growth_op_snapshot(conn: sqlite3.Connection, batch: str, as_of: str) -> dict[str, dict[str, object]]:
    q = """
    SELECT company, op_geom_1y_mcum, op_geom_2y_mcum, op_geom_4y_mcum
    FROM ttm_metric_growth_series
    WHERE batch_label = ? AND ttm_end_term = ?
    """
    out: dict[str, dict[str, object]] = {}
    for r in conn.execute(q, (batch, as_of)):
        co = str(r[0])
        out[co] = {
            "op_geom_1y_mcum": r[1],
            "op_geom_2y_mcum": r[2],
            "op_geom_4y_mcum": r[3],
        }
    return out


def _op_geom_passes(row: dict[str, object]) -> bool:
    k1, k2, k4 = "op_geom_1y_mcum", "op_geom_2y_mcum", "op_geom_4y_mcum"
    v1, v2, v4 = row.get(k1), row.get(k2), row.get(k4)
    if _is_null(v1) or _is_null(v2) or _is_null(v4):
        return False
    y1, y2, y4 = float(v1), float(v2), float(v4)
    return y1 > 0 and y2 > 0 and y4 > 0 and y2 > y4


def _last_n_quarters_op_ps_positive(
    conn: sqlite3.Connection,
    company: str,
    anchor: str,
    computed_at: str,
    as_of: str,
    min_q: int,
) -> bool:
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
    min_q: int = 28,
    mcap_csv: Path = MCAP_CSV,
    growth_db: Path = GROWTH_DB,
    val_db: Path = VAL_DB,
) -> tuple[str, list[str]]:
    """
    §3.3 스모크 통과 종목명 (mcap_top_200 순서).
    반환: (as_of, names).
    """
    if not mcap_csv.is_file():
        raise FileNotFoundError(mcap_csv)
    if not growth_db.is_file():
        raise FileNotFoundError(growth_db)
    if not val_db.is_file():
        raise FileNotFoundError(val_db)
    mcap = pd.read_csv(mcap_csv, dtype={"Code": str})
    names = [str(x).strip() for x in mcap["Name"].tolist()]

    gconn = sqlite3.connect(growth_db)
    as_res = as_of or _default_as_of_growth(gconn)
    if not as_res:
        gconn.close()
        raise RuntimeError("as_of 를 정할 수 없습니다 (growth 비었을 수 있음).")
    batch = _main_batch(gconn)
    n_by_c = _growth_n_terms(gconn, batch, as_res)
    g_snap = _growth_op_snapshot(gconn, batch, as_res)
    gconn.close()

    vconn = sqlite3.connect(val_db)
    v_snap = _snapshot_by_company(vconn, as_res)

    passed: list[str] = []
    for n in names:
        if n_by_c.get(n, 0) < min_q:
            continue
        if n not in g_snap:
            continue
        if not _op_geom_passes(g_snap[n]):
            continue
        if n not in v_snap:
            continue
        ct, _ = v_snap[n]
        if not _last_n_quarters_op_ps_positive(vconn, n, as_res, ct, as_res, min_q):
            continue
        passed.append(n)
    vconn.close()
    return as_res, passed


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", type=str, default=None)
    p.add_argument("--min-q", type=int, default=28)
    p.add_argument("--list-pass", action="store_true")
    args = p.parse_args()

    try:
        as_of, name_list = large_growth_passing_names(
            as_of=args.as_of,
            min_q=args.min_q,
            mcap_csv=MCAP_CSV,
            growth_db=GROWTH_DB,
            val_db=VAL_DB,
        )
    except FileNotFoundError as e:
        print(f"Missing {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    mcap = pd.read_csv(MCAP_CSV, dtype={"Code": str})
    names = [str(x).strip() for x in mcap["Name"].tolist()]

    gconn = sqlite3.connect(GROWTH_DB)
    batch = _main_batch(gconn)
    n_by_c = _growth_n_terms(gconn, batch, as_of)
    g_snap = _growth_op_snapshot(gconn, batch, as_of)
    gconn.close()

    vconn = sqlite3.connect(VAL_DB)
    v_snap = _snapshot_by_company(vconn, as_of)
    n_anchor = sum(1 for n in names if n_by_c.get(n, 0) >= args.min_q)
    n_g = sum(1 for n in names if n in g_snap)
    n_val = sum(1 for n in names if n in v_snap)
    n_op28 = 0
    for n in names:
        if n not in v_snap:
            continue
        ct, _ = v_snap[n]
        if _last_n_quarters_op_ps_positive(vconn, n, as_of, ct, as_of, args.min_q):
            n_op28 += 1
    vconn.close()

    print(f"as_of={as_of}  growth_batch={batch}")
    print(f"mcap names: {len(names)}")
    print(f"growth DISTINCT terms <= as_of >= {args.min_q}: {n_anchor}")
    print(f"growth as_of row (op cols): {n_g}")
    print(f"valuation as_of snapshot row: {n_val}")
    print(f"last {args.min_q} terms op_ps > 0 (valuation): {n_op28}")
    print(f"PASS §3.3 (growth op 부등식 + op_ps 28분기): {len(name_list)}")
    if args.list_pass:
        for n in name_list:
            print(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
