"""
`ttm_metric_growth.db` 에서 종목별 성장률 시계열을 읽어 터미널에 표시하거나 DataFrame 으로 반환한다.

  .venv/bin/python scripts/screening/ttm_metric_growth_lookup.py --company 삼성전자
  .venv/bin/python scripts/screening/ttm_metric_growth_lookup.py --company 삼성전자 --view wide
  .venv/bin/python scripts/screening/ttm_metric_growth_lookup.py --list-batches

노트북:
  from scripts.screening.ttm_metric_growth_lookup import load_company_growth_df
  display(load_company_growth_df("삼성전자"))
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

from scripts.screening.ttm_metric_growth import print_growth_split, print_growth_wide
from scripts.screening.ttm_metric_growth_top_n import DEFAULT_GROWTH_DB, GROWTH_TABLE

_META_DROP = (
    "batch_label",
    "source_anchor_term",
    "source_ttm_computed_at",
    "source_top_n",
)


def resolve_default_batch_label(con: sqlite3.Connection) -> str | None:
    """행 수가 가장 많은 batch_label (보통 전 종목 풀 리빌드)."""
    cur = con.execute(
        f"SELECT batch_label FROM {GROWTH_TABLE} "
        "GROUP BY batch_label ORDER BY COUNT(*) DESC LIMIT 1"
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def load_company_growth_df(
    company: str,
    *,
    growth_db: Path | None = None,
    batch_label: str | None = None,
    drop_source_meta: bool = True,
) -> pd.DataFrame:
    """
    `ttm_metric_growth_series` 에서 해당 종목·배치 행만 읽는다.
    `batch_label` 이 None 이면 행 수 최대 배치를 고른다.
    """
    path = growth_db or DEFAULT_GROWTH_DB
    if not path.is_file():
        raise FileNotFoundError(f"growth db not found: {path}")
    con = sqlite3.connect(str(path))
    try:
        bl = batch_label or resolve_default_batch_label(con)
        if not bl:
            return pd.DataFrame()
        df = pd.read_sql_query(
            f"SELECT * FROM {GROWTH_TABLE} "
            "WHERE company = ? AND batch_label = ? "
            "ORDER BY ttm_end_term ASC",
            con,
            params=(company, bl),
        )
    finally:
        con.close()
    if df.empty:
        return df
    if drop_source_meta:
        drop = [c for c in _META_DROP if c in df.columns]
        if drop:
            df = df.drop(columns=drop)
    return df


def list_batches(growth_db: Path) -> pd.DataFrame:
    con = sqlite3.connect(str(growth_db))
    try:
        df = pd.read_sql_query(
            f"""
            SELECT batch_label,
                   COUNT(*) AS n_rows,
                   COUNT(DISTINCT company) AS n_companies,
                   MAX(source_top_n) AS source_top_n_max
            FROM {GROWTH_TABLE}
            GROUP BY batch_label
            ORDER BY n_rows DESC
            """,
            con,
        )
    finally:
        con.close()
    return df


def main() -> int:
    p = argparse.ArgumentParser(
        description="ttm_metric_growth.db → 종목별 조회 (split/wide, ttm_metric_growth.py 와 동일 표 형식)",
    )
    p.add_argument("--company", default=None, help="종목명 (stock_listing Name)")
    p.add_argument(
        "--growth-db",
        type=Path,
        default=DEFAULT_GROWTH_DB,
        help="ttm_metric_growth.db 경로",
    )
    p.add_argument(
        "--batch-label",
        default=None,
        help="배치 (미지정 시 행 수 최대 batch_label)",
    )
    p.add_argument(
        "--view",
        choices=("split", "wide"),
        default="split",
        help="split=지표별 표(기본), wide=전열",
    )
    p.add_argument(
        "--list-batches",
        action="store_true",
        help="배치 목록만 출력하고 종료",
    )
    args = p.parse_args()

    if not args.growth_db.is_file():
        print(f"DB 없음: {args.growth_db}", file=sys.stderr)
        return 1

    if args.list_batches:
        bdf = list_batches(args.growth_db)
        pd.set_option("display.unicode.east_asian_width", True)
        with pd.option_context("display.width", 120, "display.max_rows", 50):
            print(bdf.to_string(index=False))
        return 0

    if not args.company:
        print("--company 가 필요합니다 (--list-batches 가 아니면).", file=sys.stderr)
        return 2

    try:
        raw = load_company_growth_df(
            args.company,
            growth_db=args.growth_db,
            batch_label=args.batch_label,
            drop_source_meta=False,
        )
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    if raw.empty:
        print(
            f"'{args.company}' 데이터 없음 (배치·종목 확인, --list-batches).",
            file=sys.stderr,
        )
        return 3

    bl = raw["batch_label"].iloc[0] if "batch_label" in raw.columns else args.batch_label
    print(
        f"growth_db={args.growth_db}  batch_label={bl}  "
        f"company={args.company}  rows={len(raw)}",
        file=sys.stderr,
    )

    g = raw.drop(columns=[c for c in _META_DROP if c in raw.columns])

    pd.set_option("display.unicode.east_asian_width", True)
    if args.view == "wide":
        print_growth_wide(g, args.company)
    else:
        print_growth_split(g, args.company)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
