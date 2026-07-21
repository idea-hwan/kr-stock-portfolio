from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from time import sleep

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.quarter_terms import iter_terms
from scripts.stock_db import (
    BASE_DIR,
    FS_DB,
    STOCK_LISTING_PATH,
    listing_instrument_exclusion_mask,
    load_listing_dataframe,
)


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    )
    return cur.fetchone() is not None


def _load_codes_from_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return sorted({line.strip().zfill(6) for line in lines if line.strip()})


def _codes_to_pairs(codes: list[str]) -> list[tuple[str, str]]:
    """리스트에 있는 코드만 listing 에서 찾고, 파이프라인과 동일하게 제외 종목은 건너뜀."""
    df = load_listing_dataframe().copy()
    df["Code"] = (
        df["Code"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    want = {str(c).strip().zfill(6) for c in codes}
    raw_match = df.loc[df["Code"].isin(want)].copy()
    missing_from_csv = sorted(want - set(raw_match["Code"].tolist()))
    if missing_from_csv:
        print(
            f"Warning: {len(missing_from_csv)} codes not in stock_listing.csv (skipped): "
            f"{missing_from_csv[:10]}..."
        )
    sub = raw_match
    if "Dept" not in sub.columns:
        sub["Dept"] = pd.NA
    before_f = len(sub)
    sub = sub.loc[~listing_instrument_exclusion_mask(sub)]
    dropped_f = before_f - len(sub)
    if dropped_f:
        print(f"Excluded {dropped_f} row(s) by instrument filter (same as DART pipeline).")
    sub["Name"] = sub["Name"].astype(str).str.strip()
    return list(zip(sub["Code"].tolist(), sub["Name"].tolist()))


def _data_dirs() -> tuple[Path, Path, Path]:
    root = (BASE_DIR / "data").resolve()
    return root / "financial_statement", root / "dividend", root / "stocks"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill only new listing symbols into existing per-term DBs."
    )
    parser.add_argument(
        "--codes-file",
        type=Path,
        default=BASE_DIR / "stock_data" / "new_codes_since_stock_csv.txt",
    )
    parser.add_argument(
        "--start-term",
        default="2023Q1",
        help="신규 종목 백필은 기본 최근 3년 분기(2023Q1~2025Q4). 과거 전체가 필요하면 예: 2015Q4",
    )
    parser.add_argument("--end-term", default="2025Q4")
    parser.add_argument(
        "--types",
        nargs="+",
        choices=["financial_statement", "dividend", "stocks"],
        default=["financial_statement", "dividend", "stocks"],
    )
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Call API and replace table even if it already exists",
    )
    args = parser.parse_args()

    codes = _load_codes_from_file(args.codes_file)
    pairs = _codes_to_pairs(codes)
    print(
        "Filter: 우선주·스팩·리츠·펀드·신탁·SPAC(부)·KONEX·KOSDAQ GLOBAL 제외 (DART 적재와 동일)."
    )
    if not pairs:
        print("No pairs to backfill.")
        return

    skip_existing = not args.no_skip_existing
    db_api = FS_DB()
    fin_dir, div_dir, stk_dir = _data_dirs()

    print(
        f"Backfill: {len(pairs)} symbols, terms {args.start_term}..{args.end_term}, "
        f"types={','.join(args.types)}, skip_existing={skip_existing}, "
        f"data={fin_dir.parent}"
    )

    for year, quarter, term in iter_terms(args.start_term, args.end_term):
        print(f"\n== {term} ==")
        if "financial_statement" in args.types:
            path = fin_dir / f"{term}.db"
            if not path.exists():
                print(f"  skip financial_statement: missing {path}")
            else:
                con = sqlite3.connect(path)
                try:
                    for code, name in pairs:
                        if skip_existing and _table_exists(con, name):
                            continue
                        try:
                            print(f"  FS {name} ({code}) ...")
                            data = db_api.finstate_data(code, year, quarter, name=name)
                            data.to_sql(name, con, if_exists="replace")
                        except Exception:
                            print(f"    -> no/empty data")
                        sleep(args.sleep)
                finally:
                    con.commit()
                    con.close()

        if "dividend" in args.types:
            path = div_dir / f"{term}.db"
            if not path.exists():
                print(f"  skip dividend: missing {path}")
            else:
                con = sqlite3.connect(path)
                try:
                    for code, name in pairs:
                        if skip_existing and _table_exists(con, name):
                            continue
                        try:
                            print(f"  DIV {name} ({code}) ...")
                            data = db_api.dividend_data(code, year, quarter, name=name)
                            data.to_sql(name, con, if_exists="replace")
                        except Exception:
                            print(f"    -> no/empty data")
                        sleep(args.sleep)
                finally:
                    con.commit()
                    con.close()

        if "stocks" in args.types:
            path = stk_dir / f"{term}.db"
            if not path.exists():
                print(f"  skip stocks: missing {path}")
            else:
                con = sqlite3.connect(path)
                try:
                    for code, name in pairs:
                        if skip_existing and _table_exists(con, name):
                            continue
                        try:
                            print(f"  STK {name} ({code}) ...")
                            data = db_api.stock_data(code, year, quarter, name=name)
                            data.to_sql(name, con, if_exists="replace")
                        except Exception:
                            print(f"    -> no/empty data")
                        sleep(args.sleep)
                finally:
                    con.commit()
                    con.close()

    print("\nBackfill finished.")


if __name__ == "__main__":
    main()
