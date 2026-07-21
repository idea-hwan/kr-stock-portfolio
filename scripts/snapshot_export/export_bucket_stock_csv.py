"""
버킷별 동일 포맷 스냅샷 CSV 저장 (stock_classification.db 미사용).

스키마·행 생성은 `stock_snapshot_core.build_stock_snapshot_df` 단일 근거.
여기서는 버킷별 유니버스만 정해 `write_universe_snapshot_csv` 로 저장한다.
유니버스 정의는 `docs/stock_classification.md` §3.x 스모크와 동일 로직을 쓴다.

  .venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket cyclical
  .venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket large_value
  .venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket large_growth
  .venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis.screen_large_asset_mcap200 import large_value_passing_names
from scripts.analysis.screen_large_growth_mcap200 import large_growth_passing_names
from scripts.snapshot_export.stock_snapshot_core import write_universe_snapshot_csv
from scripts.snapshot_export.stock_bucket_universe import cyclical_manual_universe
from scripts.snapshot_export.stock_snapshot_paths import (
    BUCKET_KEYS,
    DEFAULT_BUCKET_CSV,
    DEFAULT_CYCLICAL_MANUAL_TXT,
    DEFAULT_GROWTH_DB,
)
from scripts.analysis.ttm_valuation_df import DEFAULT_DB


def _resolve_names(
    bucket: str,
    *,
    as_of: str | None,
    min_q: int,
    cyclical_manual: Path,
) -> tuple[str | None, list[str]]:
    if bucket == "cyclical":
        if not cyclical_manual.is_file():
            raise FileNotFoundError(str(cyclical_manual))
        names = cyclical_manual_universe(cyclical_manual)
        return None, names
    if bucket == "large_value":
        a, names = large_value_passing_names(as_of=as_of, min_q=min_q)
        return a, names
    if bucket == "large_growth":
        a, names = large_growth_passing_names(as_of=as_of, min_q=min_q)
        return a, names
    raise ValueError(bucket)


def main() -> int:
    p = argparse.ArgumentParser(description="버킷별 공통 포맷 stock 스냅샷 CSV")
    p.add_argument(
        "--bucket",
        choices=[*BUCKET_KEYS, "all"],
        required=True,
        help="저장할 버킷 (all = 세 파일 각각 기본 경로에 저장)",
    )
    p.add_argument("--as-of", default=None, help="large_* 의 분기 앵커 (기본: growth·valuation DB MAX)")
    p.add_argument(
        "--min-q",
        type=int,
        default=28,
        help="성장·밸류 스크린의 DISTINCT 분기 하한 (기본 28)",
    )
    p.add_argument(
        "--cyclical-manual",
        type=Path,
        default=DEFAULT_CYCLICAL_MANUAL_TXT,
        help="cyclical 버킷 수동 유니버스 (cyclical_manual_universe.txt)",
    )
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="ttm_valuation.db")
    p.add_argument("--growth-db", type=Path, default=DEFAULT_GROWTH_DB, help="ttm_metric_growth.db")
    p.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="단일 버킷일 때 출력 경로 (--bucket all 이면 무시)",
    )
    p.add_argument("--min-quarters", type=int, default=0, help="각 종목 앞 N분기 행 생략 (스냅샷 코어)")
    p.add_argument(
        "--forward-months",
        type=int,
        nargs="+",
        default=[12, 15, 18],
    )
    p.add_argument("--anchor-term", default=None)
    p.add_argument("--computed-at", default=None)
    p.add_argument("--sleep-sec", type=float, default=0.0)
    args = p.parse_args()

    targets: list[tuple[str, Path | None]] = []
    if args.bucket == "all":
        for b in BUCKET_KEYS:
            targets.append((b, None))
    else:
        targets.append((args.bucket, args.csv))

    any_err = False
    for bucket, csv_override in targets:
        try:
            as_note, names = _resolve_names(
                bucket,
                as_of=args.as_of,
                min_q=args.min_q,
                cyclical_manual=args.cyclical_manual,
            )
        except FileNotFoundError as e:
            print(f"[{bucket}] {e}", file=sys.stderr)
            any_err = True
            continue
        except RuntimeError as e:
            print(f"[{bucket}] {e}", file=sys.stderr)
            any_err = True
            continue
        if not names:
            print(f"[{bucket}] 유니버스 비어 있음 — 스킵", file=sys.stderr)
            any_err = True
            continue
        out = Path(csv_override) if csv_override is not None else DEFAULT_BUCKET_CSV[bucket]
        if as_note:
            print(f"[{bucket}] as_of={as_note}  n={len(names)}", file=sys.stderr, flush=True)
        else:
            print(f"[{bucket}] n={len(names)}", file=sys.stderr, flush=True)
        n_rows, n_ok, skipped = write_universe_snapshot_csv(
            names,
            out,
            db_path=args.db,
            growth_db=args.growth_db,
            min_quarters=args.min_quarters,
            forward_months=args.forward_months,
            anchor_term=args.anchor_term,
            computed_at=args.computed_at,
            sleep_sec=args.sleep_sec,
        )
        print(
            f"[{bucket}] Wrote {out}  rows={n_rows}  companies_ok={n_ok}  skipped={len(skipped)}",
            file=sys.stderr,
        )
        if skipped:
            skip_path = out.with_suffix(".skipped.tsv")
            with skip_path.open("w", encoding="utf-8") as fp:
                fp.write("company\treason\n")
                for co, reason in skipped:
                    fp.write(f"{co}\t{reason}\n")
            print(f"[{bucket}] Skipped list: {skip_path}", file=sys.stderr)

    return 1 if any_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
