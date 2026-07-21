"""
로컬 SQLite가 아니라 Open DART API를 직접 호출해, 구간·종목별로 응답 행 수를 적는다.

`update_quarter_dbs` / `stock_db.FS_DB` 와 동일한 조회 경로(finstate_all CFS→OFS, 배당·주식총수 report,
종목코드 미매칭 시 Name 폴백)를 쓴다. 빈 로컬 테이블 집계와 달리 「지금 DART가 줄 데이터가 있는지」를 본다.

주의: 종목×분기×타입마다 API를 부르므로 일일 한도·시간이 크게 든다. 먼저 소구간·소수 종목으로 시험할 것.

예 (한 종목, 최근 8분기, 재무만):
  .venv/bin/python scripts/pipeline/dart_source_screen.py 2024Q1 2025Q4 \\
    --company LG에너지솔루션 --types financial_statement --dart-sleep 0.3 \\
    -o data/analytics/dart_screen_lgensol.tsv

예 (노스팩 종목명 파일, 빈 응답·에러만 기록):
  .venv/bin/python scripts/pipeline/dart_source_screen.py 2020Q1 2025Q4 \\
    --company-names-file data/analytics/empty_source_tables_companies_no_spac_reit.txt \\
    --empty-only -o data/analytics/dart_screen_no_spac_empty.tsv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from time import sleep

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.pipeline.update_quarter_dbs import _TYPE_ORDER
from scripts.pipeline.update_stock_listing import update_stock_listing
from scripts.quarter_terms import iter_terms
from scripts.stock_db import FS_DB, company_names_top_n_by_marcap, load_company_names_frozenset


def _row_count(x: object) -> int:
    if x is None:
        return 0
    if isinstance(x, pd.DataFrame):
        return 0 if x.empty else len(x)
    try:
        return len(x)  # type: ignore[arg-type]
    except TypeError:
        return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("start_term", help="시작 분기 (예: 2020Q1)")
    p.add_argument("end_term", help="종료 분기 (예: 2025Q4)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="PATH",
        required=True,
        help="TSV 출력 경로",
    )
    p.add_argument(
        "--types",
        nargs="+",
        choices=_TYPE_ORDER,
        metavar="TYPE",
        help="조회 종류. 생략 시 세 가지 모두 (%s)." % ", ".join(_TYPE_ORDER),
    )
    p.add_argument(
        "--dart-sleep",
        type=float,
        default=0.5,
        metavar="SEC",
        help="각 (종목·분기·타입) 조회 직후 대기 초 (기본 0.5). 한도 보호용.",
    )
    p.add_argument(
        "--empty-only",
        action="store_true",
        help="행 수 0 이거나 예외인 슬롯만 TSV에 쓴다.",
    )
    p.add_argument(
        "--update-listing",
        action="store_true",
        help="시작 전 KRX stock_listing 갱신",
    )
    p.add_argument(
        "--limit-companies",
        type=int,
        default=0,
        metavar="N",
        help="디버그: 상위 N개 종목만 (0이면 제한 없음)",
    )
    p.add_argument(
        "--limit-terms",
        type=int,
        default=0,
        metavar="N",
        help="디버그: 구간 중 앞에서 N개 분기만",
    )
    filt = p.add_mutually_exclusive_group()
    filt.add_argument("--top-n", type=int, metavar="N", help="시총 상위 N개")
    filt.add_argument("--company-names-file", type=Path, metavar="PATH")
    filt.add_argument(
        "--company",
        action="append",
        default=None,
        dest="companies",
        metavar="NAME",
    )
    args = p.parse_args()
    if args.types is None:
        args.types = list(_TYPE_ORDER)
    else:
        want = set(args.types)
        args.types = [t for t in _TYPE_ORDER if t in want]
    if (
        args.top_n is None
        and args.company_names_file is None
        and not args.companies
    ):
        p.error("--top-n, --company-names-file, --company 중 하나는 필요합니다.")
    return args


def _resolve_names(args: argparse.Namespace) -> frozenset[str]:
    if args.top_n is not None:
        return company_names_top_n_by_marcap(args.top_n)
    if args.company_names_file is not None:
        names = load_company_names_frozenset(args.company_names_file)
        if not names:
            raise SystemExit("에러: --company-names-file 에 파싱된 종목명이 없습니다.")
        return names
    return frozenset(c.strip() for c in args.companies if c and str(c).strip())


def main() -> int:
    args = parse_args()
    if args.update_listing:
        print("[update-listing]", file=sys.stderr)
        update_stock_listing()
        print(file=sys.stderr)

    names = _resolve_names(args)
    pairs = FS_DB.listing_code_name_pairs(names)
    if not pairs:
        print("에러: stock_listing 과 교집합인 종목이 없습니다.", file=sys.stderr)
        return 1

    if args.limit_companies > 0:
        pairs = pairs[: args.limit_companies]
    terms = list(iter_terms(args.start_term, args.end_term))
    if args.limit_terms > 0:
        terms = terms[: args.limit_terms]

    out_path = args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    db = FS_DB()
    total_calls = len(pairs) * len(terms) * len(args.types)
    print(
        f"[dart_source_screen] 종목 {len(pairs)} × 분기 {len(terms)} × 타입 {len(args.types)} "
        f"≈ {total_calls}회 호출 (empty-only={'on' if args.empty_only else 'off'})",
        file=sys.stderr,
    )

    fields = ("code", "company", "term", "type", "rows", "status", "note")
    n_written = 0
    n_ok = n_empty = n_err = 0

    with out_path.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()

        done = 0
        for code, name in pairs:
            for year, quarter, term in terms:
                for kind in args.types:
                    note = ""
                    try:
                        if kind == "financial_statement":
                            raw = db.finstate_data(
                                code, year, quarter, name=name, verbose=False
                            )
                        elif kind == "dividend":
                            raw = db.dividend_data(
                                code, year, quarter, name=name, verbose=False
                            )
                        else:
                            raw = db.stock_data(
                                code, year, quarter, name=name, verbose=False
                            )
                        rows = _row_count(raw)
                        status = "ok" if rows > 0 else "empty"
                    except Exception as e:
                        rows = 0
                        status = "error"
                        note = str(e).replace("\t", " ")[:500]

                    if status == "ok":
                        n_ok += 1
                    elif status == "empty":
                        n_empty += 1
                    else:
                        n_err += 1

                    row = {
                        "code": code,
                        "company": name,
                        "term": term,
                        "type": kind,
                        "rows": rows,
                        "status": status,
                        "note": note,
                    }
                    if not args.empty_only or status != "ok":
                        w.writerow(row)
                        n_written += 1

                    done += 1
                    if args.dart_sleep > 0:
                        sleep(args.dart_sleep)
                    if done % 200 == 0:
                        print(
                            f"  ... {done}/{total_calls} 호출, TSV 행 {n_written}",
                            file=sys.stderr,
                        )

    print(
        f"완료: TSV {out_path} (쓴 행 {n_written}, ok/empty/error 슬롯 {n_ok}/{n_empty}/{n_err})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
