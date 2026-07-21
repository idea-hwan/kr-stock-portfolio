"""
지정 연·분기의 분기 DB를 `stock_listing.csv` 기준으로 생성한다.

기본: financial_statement → dividend → stocks 순서.
시총 상위만(삼성전자만이 아니라 같은 방식으로 10개 등): `--top-n 10`.
한 종목만: `--company 하나금융지주` (여러 번 지정 시 여러 종목).

전 종목 적재 시 기본: 우선주·스팩·리츠·펀드·신탁·SPAC(부)·KONEX·KOSDAQ GLOBAL 은
`stock_listing.csv` 기준으로 제외한다 (`stock_db.listing_instrument_exclusion_mask`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 path에 넣어 `python scripts/pipeline/...` 단독 실행 시에도 import 되게 함
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.stock_db import FS_DB, company_names_top_n_by_marcap, load_company_names_frozenset
from scripts.pipeline.update_stock_listing import update_stock_listing

_TYPE_ORDER = ["financial_statement", "dividend", "stocks"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("year", type=int, help="연도 (예: 2025)")
    p.add_argument("quarter", type=int, choices=[1, 2, 3, 4], help="분기 1~4")
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
        help="실행 전 pipeline/update_stock_listing.py 와 동일하게 KRX 리스트 갱신",
    )
    filt = p.add_mutually_exclusive_group()
    filt.add_argument(
        "--top-n",
        type=int,
        metavar="N",
        help="시총(Marcap) 상위 N개만 적재 (리스트 파일 불필요)",
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
    year, quarter = args.year, args.quarter
    term = f"{year}Q{quarter}"

    if args.update_listing:
        print("[update-listing]")
        update_stock_listing()
        print()

    if args.top_n is not None:
        try:
            names = company_names_top_n_by_marcap(args.top_n)
        except ValueError as e:
            print(f"에러: --top-n 처리 실패: {e}", file=sys.stderr)
            return 1
        print(f"[필터] 시총 상위 {args.top_n}개 ({len(names)}개 이름)")
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
        print(f"[필터] 지정 종목 {len(names)}개")
    else:
        names = None

    apply_excl = names is None
    if apply_excl:
        print(
            "[필터] 우선주·이름 스팩·리츠·펀드·신탁·Dept SPAC·KONEX·KOSDAQ GLOBAL 제외"
        )

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

    print(f"\nDone {term}: {', '.join(args.types)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
