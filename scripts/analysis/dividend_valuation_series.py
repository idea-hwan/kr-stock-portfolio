"""
C — 분배 기준 벨류에이션 (프로토타입).

배당 DB `주당 현금배당금(원)` 누적을 분기 증분으로 풀어 4분기 합(TTM 현금배당/주)을 쓰고,
B(per_share_roll4 + series_per)와 같은 **공시 앵커일·액면 보정·20일·4년** 가격배수를 붙인다.

비율: 주가 ÷ TTM 주당배당 — PER과 동일한 해석 축(높을수록 배당 대비 비쌈).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.analysis import fs_metrics as fm
from scripts.analysis.series_per import (
    _last_trade_on_or_before,
    _merge_price_ratio,
    _set_20d_4y,
    filing_anchor_date,
    stock_code_for_company,
)
from scripts.quarter_terms import iter_terms, parse_term, shift_term
from scripts.stock_db import DIVIDEND_DB_DIR, FS_DB, listing_names_ordered_by_marcap


def _list_dividend_db_terms() -> list[str]:
    terms: list[str] = []
    for p in DIVIDEND_DB_DIR.glob("*.db"):
        stem = p.stem
        if len(stem) >= 6 and "Q" in stem:
            try:
                parse_term(stem)
            except ValueError:
                continue
            terms.append(stem)
    return sorted(terms, key=lambda t: parse_term(t))


def _div_table_exists(term: str, company: str) -> bool:
    path = DIVIDEND_DB_DIR / f"{term}.db"
    if not path.is_file():
        return False
    try:
        con = sqlite3.connect(path)
        cur = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (company,),
        )
        ok = cur.fetchone() is not None
        con.close()
        return ok
    except sqlite3.Error:
        return False


def _load_dps_cum_face(db: FS_DB, term: str, company: str) -> tuple[float | None, float | None]:
    """(dps_cumulative_krw_per_share, face_value_krw)."""
    if not _div_table_exists(term, company):
        return None, None
    try:
        dfd = db.read_dividend_db(term, company)
    except Exception:
        return None, None
    se = dfd["se"].astype(str).str.strip()
    dps_cum = None
    try:
        m = dfd.loc[se == "주당 현금배당금(원)"]
        if not m.empty:
            dps_cum = fm._parse_amount(m.iloc[0].get("thstrm"))
    except Exception:
        pass
    fv = None
    try:
        m = dfd.loc[se == "주당액면가액(원)"]
        if not m.empty:
            fv = fm._parse_amount(m.iloc[0].get("thstrm"))
    except Exception:
        pass
    if dps_cum is not None:
        dps_cum = float(int(dps_cum))
    if fv is not None:
        fv = float(int(fv))
    return dps_cum, fv


def _build_dps_panel(db: FS_DB, company: str, terms: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for t in terms:
        cum, fv = _load_dps_cum_face(db, t, company)
        y, q = parse_term(t)
        rows.append(
            {
                "term": t,
                "y": y,
                "q": q,
                "dps_cum": cum,
                "face_value": fv,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    fv = pd.to_numeric(df["face_value"], errors="coerce")
    df["FaceValue_ffill"] = fv.bfill().ffill()
    return df


def _quarterly_incremental_dps(df: pd.DataFrame) -> pd.Series:
    """당기 누적 주당배당 → 분기 증분(원/주)."""
    q_dps: list[float | None] = []
    for i in range(len(df)):
        row = df.iloc[i]
        cum = row["dps_cum"]
        if cum is None or (isinstance(cum, float) and np.isnan(cum)):
            q_dps.append(None)
            continue
        y, q = int(row["y"]), int(row["q"])
        if q == 1:
            q_dps.append(float(cum))
            continue
        prev = df[(df["y"] == y) & (df["q"] == q - 1)]
        if prev.empty:
            q_dps.append(None)
            continue
        prev_cum = prev.iloc[-1]["dps_cum"]
        if prev_cum is None or (isinstance(prev_cum, float) and np.isnan(prev_cum)):
            q_dps.append(None)
            continue
        inc = float(cum) - float(prev_cum)
        q_dps.append(inc if inc >= 0 else None)
    return pd.Series(q_dps, index=df.index, dtype=object)


def compute_dps_ttm_series(
    anchor_term: str,
    company: str,
    *,
    n_quarters: int = 32,
) -> dict[str, Any]:
    """
    앵커를 끝으로 하는 TTM 주당 현금배당(4분기 증분 합) 시계열.
    """
    if n_quarters < 1:
        raise ValueError("n_quarters >= 1")

    if not _list_dividend_db_terms():
        raise FileNotFoundError("data/dividend 에 .db 분기 파일이 없습니다.")

    oldest_end = shift_term(anchor_term, -(n_quarters - 1))
    min_term = shift_term(oldest_end, -3)
    panel_terms = [t for _, _, t in iter_terms(min_term, anchor_term)]

    db = FS_DB()
    panel = _build_dps_panel(db, company, panel_terms)
    if panel.empty:
        raise ValueError(f"배당 패널 비어 있음: {company}")

    panel["q_dps"] = _quarterly_incremental_dps(panel)
    panel_idx = panel.set_index("term")

    rows_out: list[dict[str, Any]] = []
    for i in range(n_quarters):
        end_t = shift_term(anchor_term, -(n_quarters - 1 - i))
        w = [
            shift_term(end_t, -3),
            shift_term(end_t, -2),
            shift_term(end_t, -1),
            end_t,
        ]
        try:
            sub = panel_idx.loc[w]
        except KeyError:
            rows_out.append({"ttm_end_term": end_t, "error": "missing_term_in_panel"})
            continue

        qds = sub["q_dps"].tolist()
        if any(x is None or (isinstance(x, float) and np.isnan(x)) for x in qds):
            rows_out.append(
                {
                    "ttm_end_term": end_t,
                    "error": "incomplete_q_dps_window",
                    "window_terms": w,
                }
            )
            continue

        dps_ttm = float(sum(float(x) for x in qds))
        fv_end = sub.iloc[-1]["FaceValue_ffill"]
        if fv_end is not None and not pd.isna(fv_end):
            fv_end_f = float(fv_end)
        else:
            fv_end_f = None

        rows_out.append(
            {
                "ttm_end_term": end_t,
                "window_terms": w,
                "dps_quarterly_krw": [float(x) for x in qds],
                "dps_ttm_krw": dps_ttm,
                "face_value_at_end": fv_end_f,
            }
        )

    return {
        "meta": {
            "company": company,
            "anchor_term": anchor_term,
            "n_points": n_quarters,
            "track": "C_dividend_valuation",
            "note": (
                "TTM 주당현금배당 = 배당공시 누적(주당 현금배당금)의 분기 증분 4Q 합. "
                "pdps_* = 주가 ÷ 액면보정 TTM DPS (PER과 유사 축)."
            ),
        },
        "series": rows_out,
    }


def _face_value_from_dps_row(row: dict[str, Any]) -> float | None:
    v = row.get("face_value_at_end")
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _adjusted_dps_table_from_series(series: list[dict[str, Any]]) -> pd.DataFrame:
    """series_per 의 EPS 액면 보정과 동일하게 DPS_ttm 만 스케일."""
    rec: list[dict[str, Any]] = []
    for row in series:
        te = row.get("ttm_end_term")
        if not te or row.get("error"):
            continue
        te = str(te)
        dps = row.get("dps_ttm_krw")
        if dps is None:
            continue
        rec.append(
            {
                "term": te,
                "filing_date": filing_anchor_date(te),
                "FaceValue": _face_value_from_dps_row(row),
                "DPS_raw": float(dps),
            }
        )
    if not rec:
        return pd.DataFrame()

    df = pd.DataFrame(rec).sort_values("filing_date").reset_index(drop=True)
    df["FaceValue_num"] = pd.to_numeric(df["FaceValue"], errors="coerce")
    df["FaceValue_ffill"] = df["FaceValue_num"].ffill().bfill()
    if df["FaceValue_ffill"].isna().all():
        df["FaceValue_ffill"] = 1.0

    ndf = df.sort_values("filing_date", ascending=False).reset_index(drop=True)
    factors: list[float] = []
    dps_adj: list[float | None] = []
    for i in range(len(ndf)):
        fv_i = float(ndf.loc[i, "FaceValue_ffill"])
        if i == 0:
            fac = 1.0
        else:
            fv_prev = float(ndf.loc[i - 1, "FaceValue_ffill"])
            if fv_i == fv_prev:
                fac = factors[i - 1]
            else:
                fac = fv_prev / fv_i if fv_i != 0 else 1.0
        factors.append(fac)
        er = ndf.loc[i, "DPS_raw"]
        if er is None or (isinstance(er, float) and np.isnan(er)):
            dps_adj.append(None)
        else:
            dps_adj.append(float(er) * fac)
    ndf["DPS_adj"] = dps_adj
    out = ndf.sort_values("filing_date", ascending=True).reset_index(drop=True)
    return out[
        ["term", "filing_date", "FaceValue_num", "DPS_raw", "DPS_adj"]
    ]


def clear_pdps_fields(row: dict[str, Any]) -> None:
    for k in ("pdps_20d_mean", "pdps_4y_mean"):
        row[k] = None
    row.pop("pdps_filing_anchor", None)
    row.pop("pdps_dps_adjusted", None)
    row.pop("pdps_anchor_close", None)
    row.pop("pdps_anchor_trade_date", None)


def enrich_dps_series_with_pdps(r: dict[str, Any], company: str) -> None:
    """주가(FinanceDataReader)로 pdps_20d_mean, pdps_4y_mean 등 부가."""
    meta = r.setdefault("meta", {})
    series: list[dict[str, Any]] = r.get("series") or []

    code = stock_code_for_company(company)
    if not code:
        meta["pdps_error"] = f"stock_listing.csv 에서 종목명 없음: {company}"
        for row in series:
            clear_pdps_fields(row)
        return

    adj_tbl = _adjusted_dps_table_from_series(series)
    if adj_tbl.empty:
        meta["pdps_error"] = "유효한 TTM DPS 행 없음"
        for row in series:
            clear_pdps_fields(row)
        return

    pos = adj_tbl.loc[adj_tbl["DPS_adj"].notna() & (adj_tbl["DPS_adj"] > 0), "DPS_adj"]
    if pos.empty:
        meta["pdps_error"] = "양수 TTM 주당배당 구간 없음 — 가격배수 생략"
        for row in series:
            clear_pdps_fields(row)
        return

    first_d = adj_tbl["filing_date"].min()
    start = first_d - pd.DateOffset(years=5)
    t_end = max(adj_tbl["filing_date"].max(), pd.Timestamp.today().normalize()) + pd.Timedelta(
        days=14
    )

    try:
        import FinanceDataReader as fdr
    except ImportError:
        meta["pdps_error"] = "FinanceDataReader 미설치 — pip install finance-datareader"
        for row in series:
            clear_pdps_fields(row)
        return

    try:
        raw = fdr.DataReader(code, start=start, end=t_end)
    except Exception as exc:
        meta["pdps_error"] = f"주가 조회 실패 ({code}): {exc}"
        for row in series:
            clear_pdps_fields(row)
        return

    if raw is None or raw.empty:
        meta["pdps_error"] = f"주가 데이터 없음: {code}"
        for row in series:
            clear_pdps_fields(row)
        return

    px = raw.reset_index()
    date_col = "Date" if "Date" in px.columns else px.columns[0]
    px = px.rename(columns={date_col: "Date"})
    if "Close" not in px.columns:
        meta["pdps_error"] = "주가 컬럼 Close 없음"
        for row in series:
            clear_pdps_fields(row)
        return
    px["Date"] = pd.to_datetime(px["Date"]).dt.normalize()
    px = px.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")

    m_dps = _merge_price_ratio(px, adj_tbl, "DPS_adj")
    term_to_dps = dict(zip(adj_tbl["term"], adj_tbl["DPS_adj"]))
    term_to_filing = dict(zip(adj_tbl["term"], adj_tbl["filing_date"]))

    for row in series:
        clear_pdps_fields(row)
        te = row.get("ttm_end_term")
        if not te or row.get("error"):
            continue
        te = str(te)
        fd = term_to_filing.get(te)
        dps_adj = term_to_dps.get(te)

        if fd is not None:
            row["pdps_filing_anchor"] = fd.strftime("%Y-%m-%d")
        if dps_adj is not None and not (isinstance(dps_adj, float) and np.isnan(dps_adj)):
            row["pdps_dps_adjusted"] = float(dps_adj)

        today_n = pd.Timestamp.today().normalize()
        cap_d = min(pd.Timestamp(fd).normalize(), today_n) if fd is not None else today_n
        d_last = _last_trade_on_or_before(px, cap_d) if fd is not None else None
        if d_last is not None:
            hit = px.loc[px["Date"] == d_last, "Close"]
            if not hit.empty:
                row["pdps_anchor_close"] = float(hit.iloc[0])
                row["pdps_anchor_trade_date"] = d_last.strftime("%Y-%m-%d")

        _set_20d_4y(row, d_last, px, dps_adj, m_dps, "pdps_20d_mean", "pdps_4y_mean")

    meta["pdps_price_source"] = f"FinanceDataReader KRX {code} (수정주가)"
    meta["pdps_basis"] = (
        "분모 = 액면 보정 TTM 주당 현금배당(원). 앵커일 = 1Q 5/15 · 2Q 8/15 · 3Q 11/15 · 4Q 익년 3/31."
    )
    meta.pop("pdps_error", None)


def _series_to_display_df(r: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in r.get("series") or []:
        te = row.get("ttm_end_term", "")
        base: dict[str, Any] = {"ttm_end": te}
        if row.get("error"):
            base["error"] = row["error"]
            rows.append(base)
            continue
        base["error"] = ""
        base["dps_ttm"] = row.get("dps_ttm_krw")
        base["face_end"] = row.get("face_value_at_end")
        base["pdps_anchor_px"] = row.get("pdps_anchor_close")
        base["pdps_20d"] = row.get("pdps_20d_mean")
        base["pdps_4y"] = row.get("pdps_4y_mean")
        base["dps_adj"] = row.get("pdps_dps_adjusted")
        rows.append(base)
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="C: 배당 TTM 기준 주가배수(pdps) 시계열 — B와 유사한 앵커·20일·4년"
    )
    sel = p.add_mutually_exclusive_group(required=False)
    sel.add_argument("--company", default=None, help="종목명 (stock_listing Name)")
    sel.add_argument(
        "--top-n",
        type=int,
        default=None,
        metavar="N",
        help="Marcap 상위 N 종목 (미지정 시 1 = 시총 1위만)",
    )
    p.add_argument("--anchor-term", default="2025Q4", help="시계열 끝 분기")
    p.add_argument(
        "--n-points",
        type=int,
        default=32,
        help="TTM 끝점 개수 (기본 32)",
    )
    p.add_argument("--no-price", action="store_true", help="주가·pdps 생략")
    p.add_argument("--json", action="store_true", help="전체 결과 JSON")
    args = p.parse_args(argv)

    if args.company:
        names = [args.company.strip()]
    else:
        n = args.top_n if args.top_n is not None else 1
        if n < 1:
            print("에러: --top-n 은 1 이상", file=sys.stderr)
            return 1
        names = listing_names_ordered_by_marcap(market=None)[:n]

    for company in names:
        try:
            r = compute_dps_ttm_series(
                args.anchor_term,
                company,
                n_quarters=args.n_points,
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"{company}: {e}", file=sys.stderr)
            continue

        if not args.no_price:
            enrich_dps_series_with_pdps(r, company)

        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
            continue

        m = r["meta"]
        print(f"company={m['company']}  anchor={m['anchor_term']}  points={m['n_points']}")
        if m.get("pdps_error"):
            print(f"  pdps_error: {m['pdps_error']}")
        elif not args.no_price:
            print(f"  {m.get('pdps_basis', '')}")
        print()
        df = _series_to_display_df(r)
        with pd.option_context("display.max_rows", 40, "display.width", 120):
            print(df.to_string(index=False))
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
