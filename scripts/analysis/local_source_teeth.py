"""
로컬 원천 3종 DB를 읽어, 종목·분기별로 「이빨 빠짐」만 적는다.

- 한 분기에서 재무·배당·주식수가 **모두** 데이터 없음(테이블 없음 또는 COUNT=0)이면 **무시**.
- 세 타입이 **모두 OK가 아니면서** 위 「전부 없음」도 아니면 **이빨 빠짐**으로 기록.

예 (노스팩 필터 전체 1693):
  .venv/bin/python scripts/analysis/local_source_teeth.py \\
    --company-names-file data/analytics/empty_source_tables_companies_no_spac_reit.txt \\
    -o data/analytics/local_source_teeth_no_spac_reit.tsv
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.stock_db import (
    DIVIDEND_DB_DIR,
    FINANCIAL_DB_DIR,
    STOCKS_DB_DIR,
    FS_DB,
    load_company_names_frozenset,
)


def _terms_on_disk() -> list[str]:
    paths = sorted(FINANCIAL_DB_DIR.glob("*.db"))
    return sorted({p.stem for p in paths}, key=lambda t: (int(t[:4]), int(t[-1])))


def _count_rows_conn(con: sqlite3.Connection, table: str) -> tuple[bool, int]:
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    if cur.fetchone() is None:
        return False, 0
    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
    return True, int(cur.fetchone()[0])


def _ok(exists: bool, n: int) -> bool:
    return exists and n > 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--company-names-file",
        type=Path,
        required=True,
        metavar="PATH",
        help="한 줄에 하나, stock_listing 의 Name",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        metavar="PATH",
        help="이빨 빠짐 (종목×분기) TSV",
    )
    p.add_argument("--start-term", type=str, default=None, metavar="YYYYQX")
    p.add_argument("--end-term", type=str, default=None, metavar="YYYYQX")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    names = load_company_names_frozenset(args.company_names_file)
    if not names:
        print("에러: 종목명이 없습니다.", file=sys.stderr)
        return 1

    pairs = FS_DB.listing_code_name_pairs(names)
    if not pairs:
        print("에러: listing 과 교집합 종목이 없습니다.", file=sys.stderr)
        return 1

    all_terms = _terms_on_disk()
    if not all_terms:
        print("에러: financial_statement/*.db 가 없습니다.", file=sys.stderr)
        return 1

    start = args.start_term or all_terms[0]
    end = args.end_term or all_terms[-1]
    terms = [t for t in all_terms if start <= t <= end]
    if not terms:
        print("에러: 분기 구간이 비었습니다.", file=sys.stderr)
        return 1

    out_path = args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fields = (
        "code",
        "company",
        "term",
        "fs_rows",
        "div_rows",
        "st_rows",
        "hole_financial_statement",
        "hole_dividend",
        "hole_stocks",
    )

    n_teeth_rows = 0
    companies_with_teeth: set[str] = set()

    with out_path.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()

        for term in terms:
            fs_p = FINANCIAL_DB_DIR / f"{term}.db"
            div_p = DIVIDEND_DB_DIR / f"{term}.db"
            st_p = STOCKS_DB_DIR / f"{term}.db"

            con_fs = sqlite3.connect(fs_p) if fs_p.is_file() else None
            con_div = sqlite3.connect(div_p) if div_p.is_file() else None
            con_st = sqlite3.connect(st_p) if st_p.is_file() else None

            try:
                for code, company in pairs:
                    if con_fs is not None:
                        f_ex, f_n = _count_rows_conn(con_fs, company)
                    else:
                        f_ex, f_n = False, 0
                    if con_div is not None:
                        d_ex, d_n = _count_rows_conn(con_div, company)
                    else:
                        d_ex, d_n = False, 0
                    if con_st is not None:
                        s_ex, s_n = _count_rows_conn(con_st, company)
                    else:
                        s_ex, s_n = False, 0

                    ok_f = _ok(f_ex, f_n)
                    ok_d = _ok(d_ex, d_n)
                    ok_s = _ok(s_ex, s_n)

                    all_dead = not ok_f and not ok_d and not ok_s
                    if all_dead:
                        continue
                    if ok_f and ok_d and ok_s:
                        continue

                    n_teeth_rows += 1
                    companies_with_teeth.add(company)

                    def rows_label(ex: bool, n: int) -> str:
                        if not ex:
                            return "miss"
                        return str(n) if n > 0 else "0"

                    w.writerow(
                        {
                            "code": code,
                            "company": company,
                            "term": term,
                            "fs_rows": rows_label(f_ex, f_n),
                            "div_rows": rows_label(d_ex, d_n),
                            "st_rows": rows_label(s_ex, s_n),
                            "hole_financial_statement": "" if ok_f else "1",
                            "hole_dividend": "" if ok_d else "1",
                            "hole_stocks": "" if ok_s else "1",
                        }
                    )
            finally:
                if con_fs is not None:
                    con_fs.close()
                if con_div is not None:
                    con_div.close()
                if con_st is not None:
                    con_st.close()

    n_pairs = len(pairs)
    print(
        f"[local_source_teeth] 종목 {n_pairs}개, 분기 {len(terms)}개 ({terms[0]}..{terms[-1]}), "
        f"이빨 빠짐 (종목×분기) {n_teeth_rows}행, 종목 수 {len(companies_with_teeth)}",
        file=sys.stderr,
    )
    print(f"TSV: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
