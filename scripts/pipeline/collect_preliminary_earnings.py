"""
분기 마감 전 "잠정실적(연결재무제표기준영업(잠정)실적, 공정공시)" 수집 — 매출액·영업이익
얼리 시그널. 정식 분기·반기·사업보고서(finstate_all 기반 update_quarter_dbs.py)보다
몇 주 먼저 올라오는 경우가 많다.

실측 근거(2026-07-24, 삼성전자): 2026Q2(반기) 정식 마감은 8/15인데, 잠정실적은
7/7에 이미 공시됨(5주 이상 빠름). 반대로 정식 분기보고서(finstate_all)는 마감일
당일(2026Q1: 5/15)에 몰아서 나오는 경우가 흔해 마감 전엔 계속 비어 있다.

**정식 재무제표를 대체하지 않는다** — 이 공시엔 매출액·영업이익만 있고(당기순이익은
대개 "-"로 미기재, 지금 이사회 승인 시 재공시 예정이라고 명시됨), CFO·자산·자본·
주식수 등은 아예 없다. TTM·PER 등 정식 계산은 여전히
scripts/pipeline/update_quarter_dbs.py + populate_ttm_valuation.py
(automation/quarterly_financial_update.sh, 마감일 기준) 트랙이 담당한다.

수집 방법: 종목별 DART 공시 목록(dart.list)에서 "잠정" + "실적"이 포함된 공시를
찾아(정정 공시가 있으면 그 중 가장 최근 것) 본문(dart.document)을 pandas.read_html로
파싱한다. 표 구조: 구분(매출액/영업이익/당기순이익 등) × 당해실적/누계실적 × 당기·
전기·전년동기 컬럼 — "당기실적" 헤더가 있는 컬럼이 이번 분기 값이다. 단위(조원·
억원·백만원 등)는 본문의 "단위 : ..." 문구에서 추출해 원 단위로 환산한다.

결과: data/analytics/preliminary_earnings.db 의 preliminary_earnings 테이블
(company, term) 기준 idempotent upsert — 없으면 스킵, 있으면(정정 등) 덮어씀.
반복 실행 안전 — 매주 다시 걸어도 그 사이 새로 올라온 공시만 채워진다.

  .venv/bin/python scripts/pipeline/collect_preliminary_earnings.py                    # 오늘 기준 자동 판단(창 밖이면 스킵)
  .venv/bin/python scripts/pipeline/collect_preliminary_earnings.py --term 2026Q2
  .venv/bin/python scripts/pipeline/collect_preliminary_earnings.py --term 2026Q2 --top-n 50
  .venv/bin/python scripts/pipeline/collect_preliminary_earnings.py --term 2026Q2 --company 삼성전자
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path
from time import sleep

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "automation") not in sys.path:
    sys.path.insert(0, str(_ROOT / "automation"))

from scripts.stock_db import FS_DB, company_names_top_n_by_marcap  # noqa: E402
from quarterly_term_window import preliminary_target_term, term_deadline  # noqa: E402

OUT_DB = _ROOT / "data" / "analytics" / "preliminary_earnings.db"

_UNIT_MULT = {"조원": 10**12, "억원": 10**8, "백만원": 10**6, "천원": 10**3, "원": 1}
_TITLE_PATTERN = re.compile(r"잠정.*실적|잠정\s*영업실적")
_ITEMS = ("매출액", "영업이익", "당기순이익")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--term", help="예: 2026Q2. 생략하면 오늘 날짜로 자동 판단(창 밖이면 종료).")
    p.add_argument("--top-n", type=int, default=200, help="시총 상위 N개 (기본 200 = mcap_top_200)")
    p.add_argument("--company", action="append", help="종목명 지정(여러 번 가능, --top-n 대신)")
    return p.parse_args()


def _init_db(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS preliminary_earnings (
            term TEXT NOT NULL,
            code TEXT NOT NULL,
            company TEXT NOT NULL,
            rcept_no TEXT,
            rcept_dt TEXT,
            unit_label TEXT,
            revenue_krw INTEGER,
            operating_income_krw INTEGER,
            net_income_krw INTEGER,
            fetched_at TEXT,
            PRIMARY KEY (term, code)
        )
        """
    )
    con.commit()


_Q_END_MONTH_DAY = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _quarter_bounds(term: str) -> tuple[date, date]:
    year, quarter = int(term[:4]), int(term[-1])
    q_start_month = {1: 1, 2: 4, 3: 7, 4: 10}[quarter]
    end_month, end_day = _Q_END_MONTH_DAY[quarter]
    return date(year, q_start_month, 1), date(year, end_month, end_day)


def _find_disclosure(dart, code: str, name: str, term: str) -> tuple[str, str] | None:
    q_start, q_end = _quarter_bounds(term)
    start = q_end + timedelta(days=1)
    end = min(date.today(), term_deadline(term))
    if start > end:
        return None
    try:
        df = dart.list(code, start=start.isoformat(), end=end.isoformat())
    except Exception:
        return None
    if df is None or df.empty:
        return None
    mask = df["report_nm"].str.contains(_TITLE_PATTERN, na=False)
    hits = df.loc[mask].sort_values("rcept_dt")
    if hits.empty:
        return None
    latest = hits.iloc[-1]  # 정정 공시가 있으면 날짜상 가장 최근 것(원본을 대체)
    return str(latest["rcept_no"]), str(latest["rcept_dt"])


def _parse_unit(html: str) -> tuple[str | None, int | None]:
    m = re.search(r"단위\s*[:：]\s*([가-힣]+)", html)
    if not m:
        return None, None
    label = m.group(1)
    return label, _UNIT_MULT.get(label)


def _parse_period(tables: list[pd.DataFrame]) -> tuple[date, date] | None:
    """"당기실적" 행의 실제 공시 기간 — 월간 잠정실적(일부 유통·식품·조선 계열사가
    분기 대신 매월 공시)을 걸러내기 위해 분기 전체 기간과 일치하는지 확인한다."""
    for t in tables:
        if t.shape[1] < 4:
            continue
        mask = t.iloc[:, 0].astype(str).str.strip() == "당기실적"
        if not mask.any():
            continue
        row = t.loc[mask].iloc[0]
        try:
            start = pd.to_datetime(str(row.iloc[1])).date()
            end = pd.to_datetime(str(row.iloc[3])).date()
        except (ValueError, TypeError):
            continue
        return start, end
    return None


def _parse_values(tables: list[pd.DataFrame]) -> dict[str, str | None]:
    for t in tables:
        header_row = None
        value_col = None
        for ridx in range(len(t)):
            row = t.iloc[ridx]
            hits = row[row.astype(str) == "당기실적"]
            if not hits.empty:
                header_row = ridx
                value_col = hits.index[0]
                break
        if header_row is None:
            continue
        out: dict[str, str | None] = {}
        for ridx2 in range(header_row + 1, len(t)):
            item = str(t.iloc[ridx2, 0]).strip()
            typ = str(t.iloc[ridx2, 1]).strip()
            if typ != "당해실적" or item not in _ITEMS:
                continue
            val = t.iloc[ridx2, value_col]
            out[item] = None if str(val).strip() in ("-", "nan", "None") else str(val)
        if out and any(v is not None for v in out.values()):
            return out
    return {}


def main() -> int:
    args = parse_args()

    term = args.term
    if term is None:
        term = preliminary_target_term(date.today())
        if term is None:
            print("현재 활성 공시 창 아님(잠정실적) — 스킵")
            return 0

    if args.company:
        names = frozenset(args.company)
    else:
        names = company_names_top_n_by_marcap(args.top_n)

    pairs = FS_DB.listing_code_name_pairs(names)
    if not pairs:
        print(f"{term}: 적재할 종목이 없습니다.")
        return 1

    dart = FS_DB().dart
    con = sqlite3.connect(OUT_DB)
    _init_db(con)

    found, skipped = 0, 0
    for i, (code, name) in enumerate(pairs):
        print(f"[{i + 1}/{len(pairs)}] {name}", file=sys.stderr, flush=True)
        try:
            hit = _find_disclosure(dart, code, name, term)
            if hit is None:
                skipped += 1
                sleep(1)
                continue
            rcept_no, rcept_dt = hit
            doc = dart.document(rcept_no)
            tables = pd.read_html(StringIO(doc))

            period = _parse_period(tables)
            if period is None or period != _quarter_bounds(term):
                skipped += 1  # 분기 전체가 아닌 월간 등 다른 기간의 잠정실적 — 제외
                sleep(1)
                continue

            unit_label, mult = _parse_unit(doc)
            values = _parse_values(tables)
            if not values or mult is None:
                skipped += 1
                sleep(1)
                continue

            def to_krw(v: str | None) -> int | None:
                return None if v is None else round(float(v) * mult)

            con.execute(
                """
                INSERT INTO preliminary_earnings
                    (term, code, company, rcept_no, rcept_dt, unit_label,
                     revenue_krw, operating_income_krw, net_income_krw, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(term, code) DO UPDATE SET
                    company=excluded.company, rcept_no=excluded.rcept_no,
                    rcept_dt=excluded.rcept_dt, unit_label=excluded.unit_label,
                    revenue_krw=excluded.revenue_krw,
                    operating_income_krw=excluded.operating_income_krw,
                    net_income_krw=excluded.net_income_krw,
                    fetched_at=excluded.fetched_at
                """,
                (
                    term, code, name, rcept_no, rcept_dt, unit_label,
                    to_krw(values.get("매출액")),
                    to_krw(values.get("영업이익")),
                    to_krw(values.get("당기순이익")),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            con.commit()
            found += 1
        except Exception as e:
            print(f"  {name}: 실패 {e!r}", file=sys.stderr)
            skipped += 1
        sleep(1)

    con.close()
    print(f"{term}: 잠정실적 확보 {found}종목, 아직 없음/실패 {skipped}종목 (전체 {len(pairs)}종목)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
