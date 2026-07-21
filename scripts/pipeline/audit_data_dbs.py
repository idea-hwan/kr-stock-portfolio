"""
분기별 SQLite DB(data/financial_statement, dividend, stocks) 전수 점검.

기본: 2015Q4 ~ 2025Q4 파일 존재, 테이블·행 요약, stocks 초기 빈 구간 알림.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.quarter_terms import iter_terms
from scripts.stock_db import BASE_DIR, listing_pipeline_allowed_names


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-term", default="2015Q4")
    p.add_argument("--end-term", default="2025Q4")
    p.add_argument(
        "--cross-diff",
        type=int,
        default=200,
        help="같은 분기에서 세 DB nonempty 테이블 수 max-min이 이 값 초과면 출력 (0이면 생략)",
    )
    return p.parse_args()


def analyze_db(path: Path) -> tuple[int, int, int]:
    """(테이블 수, 행이 1개 이상인 테이블 수, 모든 테이블 행 합)"""
    con = sqlite3.connect(path)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        names = [r[0] for r in cur.fetchall()]
        nonempty = 0
        total_rows = 0
        for name in names:
            cur.execute(f'SELECT COUNT(*) FROM "{name}"')
            c = int(cur.fetchone()[0])
            total_rows += c
            if c > 0:
                nonempty += 1
        return len(names), nonempty, total_rows
    finally:
        con.close()


def main() -> int:
    args = parse_args()
    root = (BASE_DIR / "data").resolve()
    kinds = [
        ("financial_statement", root / "financial_statement"),
        ("dividend", root / "dividend"),
        ("stocks", root / "stocks"),
    ]

    terms = [t for _, _, t in iter_terms(args.start_term, args.end_term)]
    if not terms:
        print("No terms in range.", file=sys.stderr)
        return 1

    listing_path = BASE_DIR / "stock_data" / "stock_listing.csv"
    n_listed_raw = n_listed_allowed = 0
    if listing_path.exists():
        n_listed_raw = len(pd.read_csv(listing_path, dtype={"Code": str}))
        try:
            n_listed_allowed = len(listing_pipeline_allowed_names())
        except Exception:
            n_listed_allowed = n_listed_raw

    missing: dict[str, list[str]] = defaultdict(list)
    paths: dict[str, dict[str, Path]] = {k: {} for k, _ in kinds}
    expected = set(terms)

    for kind, d in kinds:
        if not d.is_dir():
            print(f"ERROR: directory missing: {d}", file=sys.stderr)
            return 1
        for term in terms:
            p = d / f"{term}.db"
            if not p.exists():
                missing[kind].append(term)
            else:
                paths[kind][term] = p
        extra = sorted(p.stem for p in d.glob("*.db") if p.stem not in expected)
        if extra:
            tail = extra[:10]
            more = f"... (+{len(extra) - 10})" if len(extra) > 10 else ""
            print(f"WARNING [{kind}] .db files outside range: {tail}{more}")

    print("=" * 60)
    print(
        f"data root: {root}\n"
        f"range: {args.start_term} .. {args.end_term} ({len(terms)} terms)\n"
    )

    print("1) 분기 파일 존재")
    ok_files = True
    for kind, _ in kinds:
        m = missing[kind]
        print(f"   {kind:22} {len(paths[kind])}/{len(terms)}  missing={len(m)}")
        if m:
            ok_files = False
            print(f"      missing: {m[:8]}{'...' if len(m) > 8 else ''}")
    if not ok_files:
        print("\nFAIL: missing quarterly .db files.", file=sys.stderr)
        return 1

    rows_summary: list[dict] = []
    for term in terms:
        row: dict = {"term": term}
        for kind, _ in kinds:
            p = paths[kind][term]
            nt, nn, nr = analyze_db(p)
            row[kind] = (nt, nn, nr)
        rows_summary.append(row)

    print(
        "\n2) 테이블·행 요약 (리스트: CSV {}행, 적재·분석 허용 종목명 ≈ {})".format(
            n_listed_raw or "?",
            n_listed_allowed or "?",
        )
    )
    for kind, _ in kinds:
        vals = [r[kind] for r in rows_summary]
        nts = [v[0] for v in vals]
        nns = [v[1] for v in vals]
        print(f"   [{kind}]")
        print(f"      table count     min={min(nts)} max={max(nts)}")
        print(f"      nonempty tables min={min(nns)} max={max(nns)}")

    if args.cross_diff > 0:
        print(
            f"\n3) 같은 분기 fs/div/stocks nonempty 차이 > {args.cross_diff} "
            "(재무가 적은 것은 흔함)"
        )
        for r in rows_summary:
            a, b, c = r["financial_statement"][1], r["dividend"][1], r["stocks"][1]
            if max(a, b, c) - min(a, b, c) > args.cross_diff:
                print(f"   {r['term']}: fs={a} div={b} stk={c}")

    print("\n4) stocks nonempty < 50 (2015Q4~2017Q4 원천 특성 가능)")
    for r in rows_summary:
        v = r["stocks"]
        if v[1] < 50:
            print(f"   {r['term']}: nonempty={v[1]}")

    print("\n5) financial_statement 총 행 수 0인 분기")
    bad_fs = [r["term"] for r in rows_summary if r["financial_statement"][2] == 0]
    if bad_fs:
        for t in bad_fs:
            print(f"   {t}")
    else:
        print("   (없음)")

    r_last = rows_summary[-1]
    print(f"\n6) 마지막 분기 {r_last['term']}")
    for kind, _ in kinds:
        v = r_last[kind]
        print(f"   {kind}: tables={v[0]}, nonempty={v[1]}, total_rows={v[2]}")

    print("\nOK: file set complete; see notes above for expected gaps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
