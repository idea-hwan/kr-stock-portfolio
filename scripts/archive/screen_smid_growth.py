"""
§3.4 중소형 성장주 스모크: (listing 허용 − mcap_top_200) × ttm_metric_growth.db + ttm_valuation.db
  §3.3 대형 성장주와 동일하되:
  - 유니버스만 비대형 (listing_pipeline_allowed − mcap_top_200, 이름 정렬)
  - 영업(op) 대신 순이익: 최근 min-q분기 연속 ni_parent_ps > 0, as_of 행 ni_geom_* 네 부등식

  (§2 선행 버킷 미반영.)

  .venv/bin/python scripts/analysis/screen_smid_growth.py
  .venv/bin/python scripts/analysis/screen_smid_growth.py --list-pass
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

from scripts.analysis.screen_large_asset_mcap200 import (
    _last_n_quarters_all_ni_parent_positive,
    _snapshot_by_company,
)
from scripts.stock_db import listing_pipeline_allowed_names

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


def _growth_ni_snapshot(conn: sqlite3.Connection, batch: str, as_of: str) -> dict[str, dict[str, object]]:
    q = """
    SELECT company, ni_geom_1y_mcum, ni_geom_2y_mcum, ni_geom_4y_mcum
    FROM ttm_metric_growth_series
    WHERE batch_label = ? AND ttm_end_term = ?
    """
    out: dict[str, dict[str, object]] = {}
    for r in conn.execute(q, (batch, as_of)):
        co = str(r[0])
        out[co] = {
            "ni_geom_1y_mcum": r[1],
            "ni_geom_2y_mcum": r[2],
            "ni_geom_4y_mcum": r[3],
        }
    return out


def _ni_geom_passes(row: dict[str, object]) -> bool:
    k1, k2, k4 = "ni_geom_1y_mcum", "ni_geom_2y_mcum", "ni_geom_4y_mcum"
    v1, v2, v4 = row.get(k1), row.get(k2), row.get(k4)
    if _is_null(v1) or _is_null(v2) or _is_null(v4):
        return False
    y1, y2, y4 = float(v1), float(v2), float(v4)
    return y1 > 0 and y2 > 0 and y4 > 0 and y2 > y4


def smid_growth_passing_names(
    *,
    as_of: str | None = None,
    min_q: int = 28,
    mcap_csv: Path = MCAP_CSV,
    growth_db: Path = GROWTH_DB,
    val_db: Path = VAL_DB,
) -> tuple[str, list[str]]:
    """
    §3.4 스모크 통과 종목명 (listing 허용 − mcap200, 이름 정렬 순).
    반환: (as_of, names).
    """
    if not mcap_csv.is_file():
        raise FileNotFoundError(mcap_csv)
    if not growth_db.is_file():
        raise FileNotFoundError(growth_db)
    if not val_db.is_file():
        raise FileNotFoundError(val_db)
    mcap_df = pd.read_csv(mcap_csv, dtype={"Code": str})
    mcap_set = frozenset(str(x).strip() for x in mcap_df["Name"].tolist())
    allowed = listing_pipeline_allowed_names()
    universe = sorted(n for n in allowed if n not in mcap_set)

    gconn = sqlite3.connect(growth_db)
    as_res = as_of or _default_as_of_growth(gconn)
    if not as_res:
        gconn.close()
        raise RuntimeError("as_of 를 정할 수 없습니다 (growth 비었을 수 있음).")
    batch = _main_batch(gconn)
    n_by_c = _growth_n_terms(gconn, batch, as_res)
    g_snap = _growth_ni_snapshot(gconn, batch, as_res)
    gconn.close()

    vconn = sqlite3.connect(val_db)
    v_snap = _snapshot_by_company(vconn, as_res)

    passed: list[str] = []
    for n in universe:
        if n_by_c.get(n, 0) < min_q:
            continue
        if n not in g_snap:
            continue
        if not _ni_geom_passes(g_snap[n]):
            continue
        if n not in v_snap:
            continue
        ct, _ = v_snap[n]
        if not _last_n_quarters_all_ni_parent_positive(vconn, n, as_res, ct, as_res, min_q):
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
        as_of, name_list = smid_growth_passing_names(
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

    mcap_df = pd.read_csv(MCAP_CSV, dtype={"Code": str})
    mcap_set = frozenset(str(x).strip() for x in mcap_df["Name"].tolist())
    allowed = listing_pipeline_allowed_names()
    universe = sorted(n for n in allowed if n not in mcap_set)

    gconn = sqlite3.connect(GROWTH_DB)
    batch = _main_batch(gconn)
    n_by_c = _growth_n_terms(gconn, batch, as_of)
    g_snap = _growth_ni_snapshot(gconn, batch, as_of)
    gconn.close()

    vconn = sqlite3.connect(VAL_DB)
    v_snap = _snapshot_by_company(vconn, as_of)
    n_anchor = sum(1 for n in universe if n_by_c.get(n, 0) >= args.min_q)
    n_g = sum(1 for n in universe if n in g_snap)
    n_val = sum(1 for n in universe if n in v_snap)
    n_ni28 = 0
    for n in universe:
        if n not in v_snap:
            continue
        ct, _ = v_snap[n]
        if _last_n_quarters_all_ni_parent_positive(vconn, n, as_of, ct, as_of, args.min_q):
            n_ni28 += 1
    vconn.close()

    print(f"as_of={as_of}  growth_batch={batch}")
    print(f"universe: listing_pipeline_allowed − mcap_top_200 = {len(universe)} names")
    print(f"growth DISTINCT terms <= as_of >= {args.min_q}: {n_anchor}")
    print(f"growth as_of row (ni cols): {n_g}")
    print(f"valuation as_of snapshot row: {n_val}")
    print(f"last {args.min_q} terms ni_parent_ps > 0 (valuation): {n_ni28}")
    print(f"PASS §3.4 (growth ni 부등식 + ni_parent_ps 28분기): {len(name_list)}")
    if args.list_pass:
        for n in name_list:
            print(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
