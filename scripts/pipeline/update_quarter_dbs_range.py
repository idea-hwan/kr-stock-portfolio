"""
구간의 모든 분기에 대해 `update_quarter_dbs` 와 동일하게 DB 적재.

예: 시총 상위 10개만 전 기간
  python scripts/pipeline/update_quarter_dbs_range.py 2015Q1 2025Q4 --top-n 10

예: 종목명 파일(한 줄에 하나, stock_listing 의 Name 과 동일)
  python scripts/pipeline/update_quarter_dbs_range.py 2015Q1 2025Q4 \\
    --company-names-file path/to/names.txt

예: 하나금융지주만 전 기간 재무·배당·주식수
  python scripts/pipeline/update_quarter_dbs_range.py 2015Q1 2025Q4 --company 하나금융지주

전 종목 구간 적재 시 기본은 우선주·스팩·리츠·펀드·신탁·SPAC(부)·KONEX·KOSDAQ GLOBAL 제외.

그다음 TTM·확인: docs/db_operations.md (usage) 의 「한 종목 전 기간」 절.

재무만 돌리려면: --types financial_statement
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.pipeline.update_quarter_dbs import _TYPE_ORDER
from scripts.pipeline.update_stock_listing import update_stock_listing
from scripts.quarter_terms import iter_terms
from scripts.stock_db import FS_DB, company_names_top_n_by_marcap, load_company_names_frozenset


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("start_term", help="시작 분기 (예: 2015Q1)")
    p.add_argument("end_term", help="종료 분기 (예: 2025Q4)")
    p.add_argument(
        "--types",
        nargs="+",
        choices=_TYPE_ORDER,
        metavar="TYPE",
        help="적재할 DB 종류. 생략 시 세 가지 모두 (%s)." % ", ".join(_TYPE_ORDER),
    )
    p.add_argument(
        "--update-listing",
        action="store_true",
        help="첫 분기 처리 전에만 KRX 리스트 갱신",
    )
    filt = p.add_mutually_exclusive_group()
    filt.add_argument(
        "--top-n",
        type=int,
        metavar="N",
        help="시총(Marcap) 상위 N개만 적재",
    )
    filt.add_argument(
        "--company-names-file",
        type=Path,
        metavar="PATH",
        help="한 줄에 하나씩 Name.",
    )
    filt.add_argument(
        "--company",
        action="append",
        default=None,
        dest="companies",
        metavar="NAME",
        help="stock_listing 의 Name. 여러 번 지정 가능.",
    )
    args = p.parse_args()
    if args.types is None:
        args.types = list(_TYPE_ORDER)
    else:
        want = set(args.types)
        args.types = [t for t in _TYPE_ORDER if t in want]
    return args


def main() -> int:
    args = parse_args()

    if args.top_n is not None:
        try:
            names = company_names_top_n_by_marcap(args.top_n)
        except ValueError as e:
            print(f"에러: --top-n 처리 실패: {e}", file=sys.stderr)
            return 1
        print(f"[필터] 시총 상위 {args.top_n}개 ({len(names)}개 이름)\n")
    elif args.company_names_file is not None:
        names = load_company_names_frozenset(args.company_names_file)
        if not names:
            print("에러: --company-names-file 에 파싱된 종목명이 없습니다.", file=sys.stderr)
            return 1
    elif args.companies:
        names = frozenset(
            c.strip() for c in args.companies if c and str(c).strip()
        )
        if not names:
            print("에러: --company 가 비었습니다.", file=sys.stderr)
            return 1
        print(f"[필터] 지정 종목 {len(names)}개\n")
    else:
        names = None

    apply_excl = names is None
    if apply_excl:
        print(
            "[필터] 우선주·이름 스팩·리츠·펀드·신탁·Dept SPAC·KONEX·KOSDAQ GLOBAL 제외\n"
        )

    first = True
    for year, quarter, term in iter_terms(args.start_term, args.end_term):
        if first and args.update_listing:
            print("[update-listing]")
            update_stock_listing()
            print()
            first = False

        db = FS_DB()
        for t in args.types:
            print(f"== {term} / {t} ==")
            if t == "financial_statement":
                db.create_finstate_db(
                    year,
                    quarter,
                    company_names=names,
                    apply_listing_exclusions=apply_excl,
                )
            elif t == "dividend":
                db.create_dividend_db(
                    year,
                    quarter,
                    company_names=names,
                    apply_listing_exclusions=apply_excl,
                )
            else:
                db.create_stock_db(
                    year,
                    quarter,
                    company_names=names,
                    apply_listing_exclusions=apply_excl,
                )

        print(f"Done {term}: {', '.join(args.types)}\n")

    print(f"Range complete: {args.start_term} .. {args.end_term}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
