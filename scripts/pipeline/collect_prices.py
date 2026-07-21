"""
`mcap_top_200` + 경기순환 수동 유니버스 + 벤치마크(KODEX 200 ETF) 종목의 일별 종가를
FinanceDataReader 로 받아 로컬에 영구 저장한다 (`us-stock-portfolio/scripts/collect_prices.py` 상응).

`series_per.py`/`populate_ttm_valuation.py` 는 건드리지 않는다 — per_ratio 계산은
여전히 그때그때 라이브 조회. 이 DB는 대시보드 수익률 컬럼·향후 재계산 속도개선을 위한
별도 캐시로, 순수 추가(additive) 작업이다.

프로젝트 루트에서:
  .venv/bin/python scripts/pipeline/collect_prices.py                  # 증분 갱신 (기본)
  .venv/bin/python scripts/pipeline/collect_prices.py --full           # 전체 종목 처음부터 재수집
  .venv/bin/python scripts/pipeline/collect_prices.py --codes-file f.txt  # 종목범위 직접 지정(한 줄 1코드)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.manual_lists import load_cyclical_manual_universe

START_DATE = "2015-01-01"
BENCHMARK_CODE = "069500"  # KODEX 200 ETF — US 레퍼런스의 SPY 상응. 유니버스에 명시적으로 포함해
                            # "벤치마크가 유니버스 밖이라 갱신에서 누락된다" 결함을 처음부터 피한다.
SLEEP_SEC = 0.3

MCAP_TOP200_CSV = _ROOT / "stock_data" / "mcap_top_200.csv"
STOCK_LISTING_CSV = _ROOT / "stock_data" / "stock_listing.csv"
CYCLICAL_MANUAL_TXT = _ROOT / "stock_data" / "cyclical_manual_universe.txt"
COMPANY_RENAMES_CSV = _ROOT / "stock_data" / "company_name_renames.csv"
DEFAULT_DB_PATH = _ROOT / "data" / "analytics" / "prices.db"


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_prices (
            code  TEXT,
            date  TEXT,
            close REAL,
            PRIMARY KEY (code, date)
        )
        """
    )
    conn.commit()


def default_universe() -> list[str]:
    """mcap_top_200 코드 ∪ cyclical 수동 유니버스 코드(top200 밖 보완) ∪ 벤치마크."""
    codes: list[str] = []

    if MCAP_TOP200_CSV.is_file():
        top200 = pd.read_csv(MCAP_TOP200_CSV, dtype={"Code": str})
        codes.extend(top200["Code"].astype(str).str.zfill(6).tolist())

    if CYCLICAL_MANUAL_TXT.is_file() and STOCK_LISTING_CSV.is_file():
        names = load_cyclical_manual_universe(CYCLICAL_MANUAL_TXT)
        listing = pd.read_csv(STOCK_LISTING_CSV, dtype={"Code": str})
        by_name = dict(zip(listing["Name"], listing["Code"].astype(str).str.zfill(6)))

        renamed: dict[str, str] = {}
        if COMPANY_RENAMES_CSV.is_file():
            renames = pd.read_csv(COMPANY_RENAMES_CSV)
            renamed = dict(zip(renames["old_name"], renames["new_name"]))

        for name in names:
            code = by_name.get(name) or by_name.get(renamed.get(name, ""))
            if code:
                codes.append(code)
            else:
                print(f"[경고] cyclical 종목 코드 미확인: {name}", file=sys.stderr)

    codes.append(BENCHMARK_CODE)

    seen: set[str] = set()
    out: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def load_codes(codes_file: Path | None) -> list[str]:
    if codes_file is None:
        return default_universe()
    lines = codes_file.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def last_dates(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT code, MAX(date) FROM daily_prices GROUP BY code").fetchall()
    return {code: d for code, d in rows if d}


def fetch_one(code: str, start: str, end: str) -> pd.DataFrame | None:
    import FinanceDataReader as fdr

    raw = fdr.DataReader(code, start=start, end=end)
    if raw is None or raw.empty or "Close" not in raw.columns:
        return None
    px = raw.reset_index()
    date_col = "Date" if "Date" in px.columns else px.columns[0]
    px = px.rename(columns={date_col: "Date"})
    px["Date"] = pd.to_datetime(px["Date"]).dt.strftime("%Y-%m-%d")
    return px[["Date", "Close"]].dropna()


def upsert(conn: sqlite3.Connection, code: str, px: pd.DataFrame) -> int:
    rows = [(code, d, float(c)) for d, c in zip(px["Date"], px["Close"])]
    conn.executemany(
        """
        INSERT INTO daily_prices (code, date, close)
        VALUES (?, ?, ?)
        ON CONFLICT(code, date) DO UPDATE SET close = excluded.close
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--full", action="store_true", help=f"전체 종목을 {START_DATE}부터 재수집")
    p.add_argument(
        "--codes-file",
        type=Path,
        default=None,
        help="종목코드 목록 파일(한 줄 1개) — 기본은 mcap_top_200+cyclical+벤치마크 자동 산출",
    )
    p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="prices.db 경로")
    args = p.parse_args()

    codes = load_codes(args.codes_file)
    if not codes:
        print("종목 코드가 비어 있음", file=sys.stderr)
        return 1

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    init_db(conn)

    existing = {} if args.full else last_dates(conn)
    today = date.today().isoformat()

    n_ok = 0
    n_err = 0
    for i, code in enumerate(codes, start=1):
        last = existing.get(code)
        if last is not None and last >= today:
            print(f"[{i}/{len(codes)}] {code} 최신 상태 — 스킵")
            continue
        start = START_DATE if last is None else (date.fromisoformat(last) + timedelta(days=1)).isoformat()

        try:
            px = fetch_one(code, start, today)
        except Exception as exc:
            print(f"[{i}/{len(codes)}] {code} 조회 실패: {exc}", file=sys.stderr)
            n_err += 1
            time.sleep(SLEEP_SEC)
            continue

        if px is None or px.empty:
            print(f"[{i}/{len(codes)}] {code} 신규 데이터 없음")
            time.sleep(SLEEP_SEC)
            continue

        n_rows = upsert(conn, code, px)
        n_ok += 1
        print(f"[{i}/{len(codes)}] {code} {start}~{today} {n_rows}행 반영")
        time.sleep(SLEEP_SEC)

    conn.close()
    print(f"완료: {n_ok}종목 갱신, {n_err}종목 실패 (전체 {len(codes)}종목)")
    return 1 if codes and n_err == len(codes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
