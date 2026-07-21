from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.stock_db import BASE_DIR


def _sql_quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _load_renames_from_listings(
    old_path: Path, new_path: Path
) -> list[tuple[str, str]]:
    old = pd.read_csv(old_path)
    new = pd.read_csv(new_path)
    if "Unnamed: 0" in old.columns:
        old = old.drop(columns=["Unnamed: 0"])
    if "Unnamed: 0" in new.columns:
        new = new.drop(columns=["Unnamed: 0"])
    old["Code"] = old["Code"].astype(str).str.zfill(6)
    new["Code"] = new["Code"].astype(str).str.zfill(6)
    merged = old.merge(new, on="Code", suffixes=("_old", "_new"))
    diff = merged[merged["Name_old"] != merged["Name_new"]]
    pairs: list[tuple[str, str]] = []
    for _, row in diff.iterrows():
        old_name = str(row["Name_old"]).strip()
        new_name = str(row["Name_new"]).strip()
        if old_name and new_name and old_name != new_name:
            pairs.append((old_name, new_name))
    return pairs


def _table_exists_sql(con: sqlite3.Connection, table_name: str) -> bool:
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    )
    return cur.fetchone() is not None


def _rename_in_db(
    db_path: Path,
    renames: list[tuple[str, str]],
    dry_run: bool,
) -> tuple[int, list[str]]:
    """
    Returns (applied_count, log_lines).
    """
    log: list[str] = []
    applied = 0
    con = sqlite3.connect(db_path)
    try:
        for old_name, new_name in renames:
            if not _table_exists_sql(con, old_name):
                continue
            if _table_exists_sql(con, new_name):
                log.append(
                    f"SKIP (target exists): {_sql_quote_ident(old_name)} -> "
                    f"{_sql_quote_ident(new_name)} in {db_path.name}"
                )
                continue
            stmt = (
                f"ALTER TABLE {_sql_quote_ident(old_name)} "
                f"RENAME TO {_sql_quote_ident(new_name)}"
            )
            log.append(f"{'[dry-run] ' if dry_run else ''}{stmt}")
            if not dry_run:
                try:
                    con.execute(stmt)
                except sqlite3.OperationalError as exc:
                    log.append(f"ERROR {db_path.name}: {old_name} -> {new_name}: {exc}")
                    continue
            applied += 1
    finally:
        if not dry_run:
            con.commit()
        con.close()
    return applied, log


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rename SQLite tables (company names) to match current listing."
    )
    parser.add_argument(
        "--old-listing",
        type=Path,
        default=BASE_DIR / "stock_data" / "stock.csv",
    )
    parser.add_argument(
        "--new-listing",
        type=Path,
        default=BASE_DIR / "stock_data" / "stock_listing.csv",
    )
    parser.add_argument(
        "--export-csv",
        type=Path,
        default=BASE_DIR / "stock_data" / "company_name_renames.csv",
        help="old_name,new_name CSV 저장",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 ALTER 하지 않고만 로그",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="파일별 모든 로그 출력",
    )
    args = parser.parse_args()

    root = (BASE_DIR / "data").resolve()
    renames = _load_renames_from_listings(args.old_listing, args.new_listing)
    if not renames:
        print("No renames from listing diff.")
        return

    args.export_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.export_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["old_name", "new_name"])
        w.writerows(renames)
    print(f"Wrote {len(renames)} pairs to {args.export_csv}")

    subdirs = ["financial_statement", "dividend", "stocks"]
    total_applied = 0
    for sub in subdirs:
        d = root / sub
        if not d.is_dir():
            print(f"Skip missing dir: {d}")
            continue
        for db_path in sorted(d.glob("*.db")):
            n, logs = _rename_in_db(db_path, renames, dry_run=args.dry_run)
            total_applied += n
            if args.verbose and logs:
                print(f"\n{db_path}:")
                for line in logs:
                    print(" ", line)
            elif n and not args.verbose:
                print(f"{db_path.name} ({sub}): renames={n}")

    mode = "dry-run" if args.dry_run else "applied"
    print(f"\nDone ({mode}). Total table renames: {total_applied}")


if __name__ == "__main__":
    main()
