"""
시총 상위 N종에 대해 `build_ttm_metric_growth_df` 를 일괄 실행한다.

  .venv/bin/python scripts/screening/ttm_metric_growth_top_n.py --top-n 2500
  .venv/bin/python scripts/screening/ttm_metric_growth_top_n.py --top-n 10
  (배치 성공 시 항상 data/analytics/ttm_metric_growth.db 적재)
  문서: docs/ttm_metric_growth.md

종목 순서: `stock_listing.csv` 의 Marcap 내림차순(우선주·스팩·리츠 등은 `stock_db` 기본 제외).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis.ttm_valuation_df import DEFAULT_DB as DEFAULT_TTM_DB
from scripts.screening.ttm_metric_growth import build_ttm_metric_growth_df
from scripts.stock_db import listing_names_ordered_by_marcap

DEFAULT_GROWTH_DB = _ROOT / "data" / "analytics" / "ttm_metric_growth.db"
GROWTH_TABLE = "ttm_metric_growth_series"


def _default_batch_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _df_for_sqlite(df: pd.DataFrame) -> pd.DataFrame:
    """Nullable Int64 등을 SQLite에 넣기 쉽게 object 캐스트."""
    out = df.copy()
    for c in out.columns:
        if str(out[c].dtype) == "Int64":
            out[c] = out[c].astype("object")
    return out


def _write_growth_sqlite(
    combined: pd.DataFrame,
    *,
    sqlite_path: Path,
    batch_label: str,
    anchor_term: str | None,
    filter_computed_at: str | None,
    top_n: int,
    replace_batch: bool,
) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    df = combined.copy()
    df.insert(0, "batch_label", batch_label)
    if anchor_term is not None:
        df.insert(2, "source_anchor_term", anchor_term)
    else:
        df.insert(2, "source_anchor_term", None)
    if filter_computed_at is not None:
        df.insert(3, "source_ttm_computed_at", filter_computed_at)
    else:
        df.insert(3, "source_ttm_computed_at", None)
    df.insert(4, "source_top_n", int(top_n))
    df = _df_for_sqlite(df)

    con = sqlite3.connect(str(sqlite_path))
    try:
        if replace_batch:
            cur = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (GROWTH_TABLE,),
            )
            if cur.fetchone() is not None:
                con.execute(
                    f"DELETE FROM {GROWTH_TABLE} WHERE batch_label = ?",
                    (batch_label,),
                )
                con.commit()
        df.to_sql(GROWTH_TABLE, con, if_exists="append", index=False)
        con.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{GROWTH_TABLE}_batch ON {GROWTH_TABLE}(batch_label)"
        )
        con.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{GROWTH_TABLE}_batch_co "
            f"ON {GROWTH_TABLE}(batch_label, company)"
        )
        con.commit()
    finally:
        con.close()


def main() -> int:
    p = argparse.ArgumentParser(description="시총 상위 N종 TTM 성장률 일괄 계산 → ttm_metric_growth.db")
    p.add_argument("--top-n", type=int, default=10, help="시총 상위 개수 (기본 10)")
    p.add_argument(
        "--market",
        default=None,
        help="예: KOSPI / KOSDAQ (미지정 시 전체 시장)",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_TTM_DB,
        help="ttm_valuation.db 경로",
    )
    p.add_argument("--anchor-term", default=None, help="예: 2025Q4")
    p.add_argument("--computed-at", default=None, help="특정 배치만")
    p.add_argument(
        "--batch-label",
        default=None,
        help="SQLite 배치 식별자 (미지정 시 UTC 시각). 같은 라벨은 기본 DELETE 후 INSERT",
    )
    p.add_argument(
        "--sqlite-append-only",
        action="store_true",
        help="SQLite: DELETE 없이 append 만 (동일 batch_label 중복 허용)",
    )
    p.add_argument(
        "--fail-fast",
        action="store_true",
        help="첫 예외에서 중단",
    )
    p.add_argument("--quiet", action="store_true", help="진행 로그 최소화")
    args = p.parse_args()

    if args.top_n < 1:
        print("--top-n 은 1 이상", file=sys.stderr)
        return 2

    ordered = listing_names_ordered_by_marcap(market=args.market)

    names = ordered[: args.top_n]
    if not names:
        print("종목 목록이 비었습니다 (stock_listing / Marcap 확인).", file=sys.stderr)
        return 3

    frames: list[pd.DataFrame] = []
    t_batch0 = time.perf_counter()
    errors: list[tuple[str, str]] = []

    for i, company in enumerate(names, 1):
        t0 = time.perf_counter()
        try:
            g = build_ttm_metric_growth_df(
                company,
                db_path=args.db,
                anchor_term=args.anchor_term,
                computed_at=args.computed_at,
            )
        except Exception as e:
            errors.append((company, str(e)))
            if args.fail_fast:
                raise
            if not args.quiet:
                print(f"[{i}/{len(names)}] {company}  ERROR: {e}", file=sys.stderr)
            continue

        ms = (time.perf_counter() - t0) * 1000.0
        if g.empty:
            if not args.quiet:
                print(f"[{i}/{len(names)}] {company}  rows=0  ({ms:.0f}ms)  skip", file=sys.stderr)
            continue

        g = g.copy()
        g.insert(0, "company", company)

        frames.append(g)
        if not args.quiet:
            print(
                f"[{i}/{len(names)}] {company}  rows={len(g)}  ({ms:.0f}ms)",
                file=sys.stderr,
            )

    elapsed = time.perf_counter() - t_batch0
    n_ok = len(frames)
    n_empty = len(names) - n_ok - len(errors)

    combined: pd.DataFrame | None = None
    if frames:
        combined = pd.concat(frames, ignore_index=True)

    if combined is None or combined.empty:
        if not args.quiet and not frames and len(names) > 0:
            print("SQLite: 적재할 행 없음 (모든 종목 empty 또는 오류)", file=sys.stderr)
    else:
        bl = args.batch_label or _default_batch_label()
        _write_growth_sqlite(
            combined,
            sqlite_path=DEFAULT_GROWTH_DB,
            batch_label=bl,
            anchor_term=args.anchor_term,
            filter_computed_at=args.computed_at,
            top_n=args.top_n,
            replace_batch=not args.sqlite_append_only,
        )
        if not args.quiet:
            print(
                f"SQLite  path={DEFAULT_GROWTH_DB}  table={GROWTH_TABLE}  "
                f"batch_label={bl}  rows={len(combined)}",
                file=sys.stderr,
            )

    if not args.quiet:
        print(
            f"done  companies_requested={len(names)}  ok={n_ok}  "
            f"empty={n_empty}  errors={len(errors)}  elapsed={elapsed:.2f}s",
            file=sys.stderr,
        )

    if errors and not args.quiet:
        for c, msg in errors[:20]:
            print(f"  error  {c}: {msg}", file=sys.stderr)
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more", file=sys.stderr)

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
