"""
전 종목 TTM·주당·PER 시계열을 `data/analytics/ttm_valuation.db` 에 적재한다.

사전 작업·실행 순서: docs/ttm_valuation.md (B 수익 기준). 분기 원천 준비·명령: docs/db_operations.md (usage, A).
  1) scripts/pipeline/update_stock_listing.py — 상장 리스트
  2) 분기별 재무·주식·배당 DB 적재
  3) 본 스크립트

갭 점검(대표 원인):
  - 재무 DB 없음 / 일부 분기만 있음 → 시계열 짧거나 행 error
  - 계정과목 매칭 실패 → 매출·CFO 등 결측, pl_roll4_dirty 다수
  - 액면·주식수 → per_eps_adjusted·PER 왜곡 (series_per 가 eps_fps 식으로 보정)
  - 주가 API 실패·한도 → per_* 결측, meta.per_error
적재 요약 말미에 앵커 행 기준 PL/CF 구조적 결측(이빨) 종목·이슈 코드를 출력하고, 갭 JSON 에도 포함한다.

예시:
  .venv/bin/python scripts/pipeline/populate_ttm_valuation.py --init-db
  .venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2025Q4 --limit 10
  .venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2025Q4 --company 삼성전자
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis.audit_ttm_pl_cf_gaps import structural_pl_cf_gaps_dataframe
from scripts.analysis.per_share_roll4 import (
    compute_ttm_series,
    infer_full_series_n_quarters,
)
from scripts.analysis.series_per import clear_per_price_fields, enrich_ttm_series_with_per
from scripts.stock_db import listing_names_ordered_by_marcap, listing_pipeline_allowed_names

ANALYTICS_DIR = _ROOT / "data" / "analytics"
DB_PATH = ANALYTICS_DIR / "ttm_valuation.db"
LISTING_PATH = _ROOT / "stock_data" / "stock_listing.csv"
LOGIC_VERSION = "ttm_v1_filing_anchor_adjfv"

DDL = """
CREATE TABLE IF NOT EXISTS ttm_valuation_series (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  computed_at           TEXT NOT NULL,
  logic_version         TEXT NOT NULL,
  company               TEXT NOT NULL,
  anchor_term           TEXT NOT NULL,
  ttm_end_term          TEXT NOT NULL,
  window_terms          TEXT,
  series_error          TEXT,

  cfo_ps                REAL,
  capex_ps              REAL,
  fcf_ps                REAL,
  rev_ps                REAL,
  gp_ps                 REAL,
  op_ps                 REAL,
  ni_parent_ps          REAL,

  fy_rev_ps             REAL,
  fy_gp_ps              REAL,
  fy_op_ps              REAL,
  fy_ni_ps              REAL,
  income_source         TEXT,

  face_value_end        REAL,
  istc_ffill_end        REAL,
  pl_dirty              TEXT,

  per_filing_anchor     TEXT,
  per_anchor_trade_date TEXT,
  per_anchor_close      REAL,
  per_eps_adjusted      REAL,
  per_20d_mean          REAL,
  per_4y_mean           REAL,
  per_op_20d_mean       REAL,
  per_op_4y_mean        REAL,
  per_gp_20d_mean       REAL,
  per_gp_4y_mean        REAL,
  per_rev_20d_mean      REAL,
  per_rev_4y_mean       REAL,
  per_fcf_20d_mean      REAL,
  per_fcf_4y_mean       REAL,
  per_run_error         TEXT,

  ttm_cfo_krw           INTEGER,
  ttm_capex_krw         INTEGER,
  ttm_fcf_krw           INTEGER,

  ni_fs_roll4_ps        REAL,
  div_ni_ps_ttm         REAL,
  div_ni_ps_fy          REAL,
  ni_eps_basis          TEXT,

  UNIQUE (computed_at, company, anchor_term, ttm_end_term)
);

CREATE INDEX IF NOT EXISTS idx_ttm_company_end
  ON ttm_valuation_series (company, ttm_end_term);
CREATE INDEX IF NOT EXISTS idx_ttm_anchor_computed
  ON ttm_valuation_series (anchor_term, computed_at);
"""


def _migrate_ttm_valuation_schema(con: sqlite3.Connection) -> None:
    cur = con.execute("PRAGMA table_info(ttm_valuation_series)")
    cols = {row[1] for row in cur.fetchall()}
    if not cols:
        return
    if "per_4y_daily_mean" in cols and "per_4y_mean" not in cols:
        con.execute(
            "ALTER TABLE ttm_valuation_series RENAME COLUMN per_4y_daily_mean TO per_4y_mean"
        )
        cols.discard("per_4y_daily_mean")
        cols.add("per_4y_mean")
    for name, typ in (
        ("per_op_20d_mean", "REAL"),
        ("per_op_4y_mean", "REAL"),
        ("per_gp_20d_mean", "REAL"),
        ("per_gp_4y_mean", "REAL"),
        ("per_rev_20d_mean", "REAL"),
        ("per_rev_4y_mean", "REAL"),
        ("per_fcf_20d_mean", "REAL"),
        ("per_fcf_4y_mean", "REAL"),
        ("ni_fs_roll4_ps", "REAL"),
        ("div_ni_ps_ttm", "REAL"),
        ("div_ni_ps_fy", "REAL"),
        ("ni_eps_basis", "TEXT"),
    ):
        if name not in cols:
            con.execute(f"ALTER TABLE ttm_valuation_series ADD COLUMN {name} {typ}")
            cols.add(name)


def _ensure_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(DDL)
        _migrate_ttm_valuation_schema(con)
        con.commit()
    finally:
        con.close()


def _refresh_listing() -> int:
    script = _ROOT / "scripts" / "pipeline" / "update_stock_listing.py"
    r = subprocess.run([sys.executable, str(script)], cwd=str(_ROOT))
    return r.returncode


def _flatten_series_row(
    computed_at: str,
    company: str,
    anchor_term: str,
    row: dict[str, Any],
    *,
    per_run_error: str | None = None,
) -> tuple[Any, ...]:
    te = row.get("ttm_end_term", "")
    w = row.get("window_terms")
    wj = json.dumps(w, ensure_ascii=False) if w else None
    err = row.get("error")

    ps = row.get("ttm_per_share_won_sum_quarters") or {}
    pl = row.get("roll4_pl_per_share_eps_fps") or {}
    fy = row.get("income_per_share_won_fy_if_q4_annual") or {}
    tk = row.get("ttm_krw") or {}
    dirty = row.get("pl_roll4_dirty")
    dj = ",".join(dirty) if dirty else None

    fy_ni_fs = fy.get("net_income_parent")
    if fy_ni_fs is not None and not (isinstance(fy_ni_fs, float) and pd.isna(fy_ni_fs)):
        fy_ni_resolved = fy_ni_fs
    else:
        fy_ni_resolved = None

    return (
        computed_at,
        LOGIC_VERSION,
        company,
        anchor_term,
        te,
        wj,
        err if err else None,
        ps.get("cfo"),
        ps.get("capex"),
        ps.get("fcf"),
        pl.get("revenue"),
        None,
        pl.get("operating_income"),
        pl.get("net_income_parent"),
        fy.get("revenue"),
        None,
        fy.get("operating_income"),
        fy_ni_resolved,
        row.get("income_source"),
        row.get("face_value_at_end"),
        row.get("istc_ffill_at_end"),
        dj,
        row.get("per_filing_anchor"),
        row.get("per_anchor_trade_date"),
        row.get("per_anchor_close"),
        row.get("per_eps_adjusted"),
        row.get("per_20d_mean"),
        row.get("per_4y_mean"),
        row.get("per_op_20d_mean"),
        row.get("per_op_4y_mean"),
        None,
        None,
        row.get("per_rev_20d_mean"),
        row.get("per_rev_4y_mean"),
        row.get("per_fcf_20d_mean"),
        row.get("per_fcf_4y_mean"),
        per_run_error,
        tk.get("cfo"),
        tk.get("capex"),
        tk.get("fcf"),
        row.get("ni_fs_roll4_ps"),
        row.get("div_ni_ps_ttm"),
        row.get("div_ni_ps_fy"),
        row.get("ni_eps_basis"),
    )


INSERT_SQL = """
INSERT OR REPLACE INTO ttm_valuation_series (
  computed_at, logic_version, company, anchor_term, ttm_end_term,
  window_terms, series_error,
  cfo_ps, capex_ps, fcf_ps, rev_ps, gp_ps, op_ps, ni_parent_ps,
  fy_rev_ps, fy_gp_ps, fy_op_ps, fy_ni_ps, income_source,
  face_value_end, istc_ffill_end, pl_dirty,
  per_filing_anchor, per_anchor_trade_date, per_anchor_close,
  per_eps_adjusted, per_20d_mean, per_4y_mean,
  per_op_20d_mean, per_op_4y_mean, per_gp_20d_mean, per_gp_4y_mean,
  per_rev_20d_mean, per_rev_4y_mean,
  per_fcf_20d_mean, per_fcf_4y_mean,
  per_run_error,
  ttm_cfo_krw, ttm_capex_krw, ttm_fcf_krw,
  ni_fs_roll4_ps, div_ni_ps_ttm, div_ni_ps_fy, ni_eps_basis
) VALUES (
  ?,?,?,?,?,?,?,
  ?,?,?,?,?,?,?,
  ?,?,?,?,?,
  ?,?,?,
  ?,?,?,?,?,?,?,?,?,?,?,?,
  ?,?,
  ?,
  ?,?,?,?,?,?,?
)
"""


def _process_company(
    con: sqlite3.Connection,
    computed_at: str,
    company: str,
    anchor_term: str,
    *,
    skip_per: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {"company": company, "rows": 0, "ok": False, "reason": None}
    try:
        n_q, _, _, _, _ = infer_full_series_n_quarters(anchor_term, company)
    except (FileNotFoundError, ValueError) as e:
        out["reason"] = f"infer_series:{e}"
        return out

    try:
        r = compute_ttm_series(anchor_term, company, n_quarters=n_q)
    except Exception as e:
        out["reason"] = f"compute:{e}"
        return out

    if not skip_per:
        enrich_ttm_series_with_per(r, company)
        per_err = (r.get("meta") or {}).get("per_error")
    else:
        per_err = None
        for row in r.get("series") or []:
            clear_per_price_fields(row)

    meta_err = per_err
    for row in r.get("series") or []:
        tup = _flatten_series_row(
            computed_at, company, anchor_term, row, per_run_error=meta_err
        )
        con.execute(INSERT_SQL, tup)
        out["rows"] += 1

    out["ok"] = True
    out["meta"] = r.get("meta")
    out["per_error"] = meta_err
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="TTM·PER 시계열 → data/analytics/ttm_valuation.db")
    p.add_argument("--term", default="2025Q4", help="앵커 분기")
    p.add_argument("--refresh-listing", action="store_true", help="적재 전 update_stock_listing.py 실행")
    p.add_argument("--market", default=None, help="예: KOSPI (미지정이면 전체 Market)")
    p.add_argument(
        "--company",
        action="append",
        default=None,
        dest="companies",
        metavar="NAME",
        help=(
            "stock_listing.csv 의 Name 과 동일한 종목명만 적재. 여러 번 지정 가능. "
            "지정 시 --limit 은 무시된다."
        ),
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="시총(Marcap) 내림차순·필터 적용 후 상위 N개만 (예: 파일럿 10)",
    )
    p.add_argument("--sleep", type=float, default=0.12, help="종목 간 대기(초), 주가 API 부하 완화")
    p.add_argument("--no-per", action="store_true", help="주가·PER 생략 (재무만 적재)")
    p.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 종목 수·샘플만")
    p.add_argument(
        "--init-db",
        action="store_true",
        help="data/analytics/ttm_valuation.db 만 생성(스키마만). 적재는 하지 않음",
    )
    args = p.parse_args()

    if args.init_db:
        _ensure_db(DB_PATH)
        print(f"초기화 완료: {DB_PATH}")
        print('확인: sqlite3 data/analytics/ttm_valuation.db ".tables"')
        return 0

    if args.refresh_listing:
        rc = _refresh_listing()
        if rc != 0:
            print("update_stock_listing.py 실패", file=sys.stderr)
            return rc

    if not LISTING_PATH.is_file():
        print("stock_listing.csv 없음. --refresh-listing 또는 리스트를 먼저 만드세요.", file=sys.stderr)
        return 1

    if args.companies:
        raw = list(
            dict.fromkeys(c.strip() for c in args.companies if c and str(c).strip())
        )
        if not raw:
            print("--company 가 비었습니다.", file=sys.stderr)
            return 1
        listing_set = set(listing_pipeline_allowed_names())
        names = []
        missing: list[str] = []
        for c in raw:
            if c in listing_set:
                names.append(c)
            else:
                missing.append(c)
        if missing:
            print(
                "허용 목록에 없는 Name (오타이거나 파이프라인에서 제외되는 종목일 수 있음): "
                + ", ".join(missing),
                file=sys.stderr,
            )
            return 1
    else:
        names = listing_names_ordered_by_marcap(market=args.market)
        if args.limit:
            names = names[: args.limit]

    computed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if args.dry_run:
        print(f"[dry-run] 종목 수={len(names)} anchor={args.term} computed_at={computed_at}")
        print("샘플:", names[:5])
        return 0

    _ensure_db(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    failures: list[tuple[str, str]] = []
    per_error_counts: Counter[str] = Counter()
    ok_companies = 0

    print(
        f"적재 시작: 종목 {len(names)}개  anchor={args.term}  "
        f"(진행 로그는 50종목마다 출력)",
        flush=True,
    )

    try:
        for i, company in enumerate(names):
            res = _process_company(
                con,
                computed_at,
                company,
                args.term,
                skip_per=args.no_per,
            )
            if res["ok"]:
                ok_companies += 1
                pe = res.get("per_error")
                if pe:
                    per_error_counts[pe[:120]] += 1
            else:
                failures.append((company, res.get("reason") or "?"))
            con.commit()
            if (i + 1) % 50 == 0 or (i + 1) == len(names):
                print(f"... {i + 1}/{len(names)}", flush=True)
            if args.sleep > 0:
                sleep(args.sleep)
    finally:
        con.close()

    con2 = sqlite3.connect(DB_PATH)
    try:
        cur = con2.execute(
            """
            SELECT COUNT(*) FROM ttm_valuation_series
            WHERE computed_at = ? AND anchor_term = ?
            """,
            (computed_at, args.term),
        )
        n_rows = cur.fetchone()[0]
        cur = con2.execute(
            """
            SELECT COUNT(DISTINCT company) FROM ttm_valuation_series
            WHERE computed_at = ? AND anchor_term = ? AND pl_dirty IS NOT NULL AND pl_dirty != ''
            """,
            (computed_at, args.term),
        )
        dirty_companies = cur.fetchone()[0]
        cur = con2.execute(
            """
            WITH latest AS (
              SELECT company, MAX(ttm_end_term) AS te
              FROM ttm_valuation_series
              WHERE computed_at = ? AND anchor_term = ?
                AND (series_error IS NULL OR series_error = '')
              GROUP BY company
            )
            SELECT COUNT(*) FROM ttm_valuation_series t
            JOIN latest l ON t.company = l.company AND t.ttm_end_term = l.te
            WHERE t.computed_at = ? AND t.anchor_term = ?
              AND t.per_20d_mean IS NULL
            """,
            (computed_at, args.term, computed_at, args.term),
        )
        missing_per_on_latest_ttm = cur.fetchone()[0]
        gap_df, n_anchor_gap = structural_pl_cf_gaps_dataframe(
            con2,
            computed_at,
            args.term,
            include_pl_dirty_only=False,
            exclude_financial_hint=False,
        )
        gap_df_nonfin, _ = structural_pl_cf_gaps_dataframe(
            con2,
            computed_at,
            args.term,
            include_pl_dirty_only=False,
            exclude_financial_hint=True,
        )
    finally:
        con2.close()

    print()
    print("=== 적재 요약 ===")
    print(f"DB: {DB_PATH}")
    print(f"computed_at: {computed_at}  anchor: {args.term}  logic: {LOGIC_VERSION}")
    print(f"시도 종목: {len(names)}  성공: {ok_companies}  실패: {len(failures)}")
    print(f"삽입 행 수: {n_rows}")
    print(f"손익 차분 dirty 표시가 한 번이라도 있는 회사 수: {dirty_companies}")
    print(
        "최신 TTM 행(오류 행 제외)에서 PER_20d 결측인 회사 수: "
        f"{missing_per_on_latest_ttm}"
    )
    if per_error_counts:
        print("PER 메타 오류(종목 수) 상위:")
        for msg, c in per_error_counts.most_common(8):
            print(f"  [{c}] {msg}")
    if failures:
        print(f"실패 샘플 (최대 15):")
        for co, rs in failures[:15]:
            print(f"  {co}: {rs}")

    print()
    print("=== 앵커 행 PL/CF 이빨 (구조적 결측, pl_dirty만 제외) ===")
    print(
        f"앵커 행 종목 수: {n_anchor_gap}  이빨 종목(전체): {len(gap_df)}  "
        f"이름 힌트로 금융 제외 시: {len(gap_df_nonfin)}"
    )
    if gap_df.empty:
        print("  (해당 없음)")
    else:
        for _, gr in gap_df.iterrows():
            print(f"  {gr['company']}: {gr['issues']}")
    print(
        "  ※ 상세 표: PYTHONPATH=. python scripts/analysis/audit_ttm_pl_cf_gaps.py "
        f"--computed-at {computed_at} --anchor-term {args.term}"
    )

    gap_path = ANALYTICS_DIR / f"ttm_valuation_gaps_{args.term}_{computed_at[:10]}.json"
    try:
        gap_path.write_text(
            json.dumps(
                {
                    "computed_at": computed_at,
                    "anchor_term": args.term,
                    "failures": [{"company": a, "reason": b} for a, b in failures],
                    "per_error_histogram": dict(per_error_counts.most_common(50)),
                    "stats": {
                        "rows": n_rows,
                        "dirty_companies": dirty_companies,
                        "companies_missing_per20d_on_latest_ttm": missing_per_on_latest_ttm,
                        "structural_pl_cf_gap_companies": len(gap_df),
                        "structural_pl_cf_gap_companies_non_financial_hint": len(
                            gap_df_nonfin
                        ),
                    },
                    "structural_pl_cf_gaps": [
                        {"company": str(r["company"]), "issues": str(r["issues"])}
                        for _, r in gap_df.iterrows()
                    ],
                    "structural_pl_cf_gaps_non_financial_hint": [
                        {"company": str(r["company"]), "issues": str(r["issues"])}
                        for _, r in gap_df_nonfin.iterrows()
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"갭 로그: {gap_path}")
    except OSError:
        pass

    return 0 if len(failures) < len(names) else 1


if __name__ == "__main__":
    raise SystemExit(main())
