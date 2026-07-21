"""
시계열(TTM 끝 분기별) 주가 ÷ 주당지표 부가 (PER, P/매출, P/영업).

공시 시점(전자공시 일반적 마감)에 맞춘 앵커일:
  1Q → 당해 5/15, 2Q → 8/15, 3Q → 11/15, 4Q → 익년 3/31 (사업보고)

액면 변경 시 eps_fps 와 동일 Adj_Factor 로 주당 매출·영업·순이익 보정.
가격배수 분모: 4Q 끝점에서 사업보고(11011) FY 주당이 양수면 FY 우선, 아니면 재무 롤4 TTM 주당(배당 공시 EPS 미사용).
일별 배수: 종가 ÷ (backward-merge 한 보정 주당값); 4y_mean 은 앵커까지 4년 일별 배수 평균.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.quarter_terms import parse_term

STOCK_LISTING_PATH = BASE_DIR / "stock_data" / "stock_listing.csv"

_ADJ_COLS = ("EPS_adj", "Rev_adj", "Op_adj")


def stock_code_for_company(company: str) -> str | None:
    if not STOCK_LISTING_PATH.is_file():
        return None
    sl = pd.read_csv(STOCK_LISTING_PATH)
    if "Name" not in sl.columns or "Code" not in sl.columns:
        return None
    m = sl.loc[sl["Name"].astype(str) == company]
    if m.empty:
        return None
    raw = m.iloc[0]["Code"]
    s = str(raw).strip().split(".")[0]
    if not s.isdigit():
        return None
    return s.zfill(6)


def filing_anchor_date(term: str) -> pd.Timestamp:
    y, q = parse_term(term)
    if q == 1:
        return pd.Timestamp(y, 5, 15)
    if q == 2:
        return pd.Timestamp(y, 8, 15)
    if q == 3:
        return pd.Timestamp(y, 11, 15)
    if q == 4:
        return pd.Timestamp(y + 1, 3, 31)
    raise ValueError(f"Invalid quarter in term: {term}")


def _positive_ps(v: Any) -> float | None:
    """주당 지표: 양수만 가격배수 분모로 사용."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _fy_first_pl_ps_for_multiples(row: dict[str, Any], pl_key: str) -> float | None:
    """
    순이익(net_income_parent): 재무 사업보고 FY(11011) → 재무 롤4 TTM만.
    그 외 지표는 4Q FY(재무) → 롤4.
    """
    if row.get("error"):
        return None
    pl = row.get("roll4_pl_per_share_eps_fps") or {}
    fy = row.get("income_per_share_won_fy_if_q4_annual") or {}
    te = str(row.get("ttm_end_term") or "")
    try:
        _, qn = parse_term(te)
    except ValueError:
        qn = 0
    r = _positive_ps(pl.get(pl_key))
    f_fs = _positive_ps(fy.get(pl_key))
    if pl_key == "net_income_parent":
        if qn == 4 and f_fs is not None:
            return f_fs
        return r
    if qn == 4 and f_fs is not None:
        return f_fs
    return r


def _face_value_from_row(row: dict[str, Any]) -> float | None:
    v = row.get("face_value_at_end")
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _adjusted_valuation_table_from_series(series: list[dict[str, Any]]) -> pd.DataFrame:
    """term, filing_date, FaceValue_num, *_raw, *_adj (액면 보정 동일 계수)."""
    rec: list[dict[str, Any]] = []
    for row in series:
        te = row.get("ttm_end_term")
        if not te or row.get("error"):
            continue
        te = str(te)
        rec.append(
            {
                "term": te,
                "filing_date": filing_anchor_date(te),
                "FaceValue": _face_value_from_row(row),
                "EPS_raw": _fy_first_pl_ps_for_multiples(row, "net_income_parent"),
                "Rev_raw": _fy_first_pl_ps_for_multiples(row, "revenue"),
                "Op_raw": _fy_first_pl_ps_for_multiples(row, "operating_income"),
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
    eps_adj: list[float | None] = []
    rev_adj: list[float | None] = []
    op_adj: list[float | None] = []

    raw_cols = ("EPS_raw", "Rev_raw", "Op_raw")
    out_lists = (eps_adj, rev_adj, op_adj)

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
        for col, lst in zip(raw_cols, out_lists):
            er = ndf.loc[i, col]
            if er is None or (isinstance(er, float) and np.isnan(er)):
                lst.append(None)
            else:
                lst.append(float(er) * fac)

    ndf["EPS_adj"] = eps_adj
    ndf["Rev_adj"] = rev_adj
    ndf["Op_adj"] = op_adj
    out = ndf.sort_values("filing_date", ascending=True).reset_index(drop=True)
    return out[
        [
            "term",
            "filing_date",
            "FaceValue_num",
            "EPS_raw",
            "EPS_adj",
            "Rev_raw",
            "Rev_adj",
            "Op_raw",
            "Op_adj",
        ]
    ]


def _any_positive_basis(adj_tbl: pd.DataFrame) -> bool:
    for c in _ADJ_COLS:
        s = adj_tbl[c]
        if s.notna().any() and (s.dropna() > 0).any():
            return True
    return False


def _last_trade_on_or_before(px: pd.DataFrame, d: pd.Timestamp) -> pd.Timestamp | None:
    sub = px.loc[px["Date"] <= pd.Timestamp(d).normalize()]
    if sub.empty:
        return None
    return pd.Timestamp(sub["Date"].iloc[-1])


def _merge_price_ratio(px: pd.DataFrame, adj_tbl: pd.DataFrame, adj_col: str) -> pd.DataFrame | None:
    sub = adj_tbl.loc[adj_tbl[adj_col].notna() & (adj_tbl[adj_col] > 0), ["filing_date", adj_col]].copy()
    if sub.empty:
        return None
    sub = sub.rename(columns={"filing_date": "Date", adj_col: "Basis"})
    sub = sub.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")
    sub2 = sub.sort_values("Date")
    m = pd.merge_asof(px, sub2, on="Date", direction="backward")
    m["Ratio"] = m["Close"] / m["Basis"]
    m["Ratio"] = m["Ratio"].replace([np.inf, -np.inf], np.nan)
    return m


def _invalid_basis(basis: float | None) -> bool:
    if basis is None:
        return True
    try:
        f = float(basis)
    except (TypeError, ValueError):
        return True
    if np.isnan(f):
        return True
    return f <= 0


def _set_20d_4y(
    row: dict[str, Any],
    d_last: pd.Timestamp | None,
    px: pd.DataFrame,
    basis: float | None,
    m_merged: pd.DataFrame | None,
    key_20d: str,
    key_4y: str,
) -> None:
    if d_last is None or _invalid_basis(basis):
        return
    px_on = px[px["Date"] <= d_last]
    if not px_on.empty:
        tail = px_on.tail(20)
        if not tail.empty:
            row[key_20d] = float(tail["Close"].mean() / basis)
    if m_merged is not None and not m_merged.empty:
        win = m_merged[
            (m_merged["Date"] > d_last - pd.DateOffset(years=4)) & (m_merged["Date"] <= d_last)
        ]
        valid = win["Ratio"].dropna()
        if len(valid) > 0:
            row[key_4y] = float(valid.mean())


def enrich_ttm_series_with_per(r: dict[str, Any], company: str) -> None:
    """
    r['series'] 각 행에 앵커·주가·PER 및 P/Rev, P/OP (20일·4년 평균) 추가.
    """
    meta = r.setdefault("meta", {})
    series: list[dict[str, Any]] = r.get("series") or []

    code = stock_code_for_company(company)
    if not code:
        meta["per_error"] = f"stock_listing.csv 에서 종목명 없음: {company}"
        for row in series:
            clear_per_price_fields(row)
        return

    adj_tbl = _adjusted_valuation_table_from_series(series)
    if adj_tbl.empty:
        meta["per_error"] = "시계열 행 없음"
        for row in series:
            clear_per_price_fields(row)
        return

    if not _any_positive_basis(adj_tbl):
        meta["per_error"] = (
            "TTM 주당 매출·영업·순이익(롤4) 양수 구간 없음 — 가격배수 생략"
        )
        for row in series:
            clear_per_price_fields(row)
        return

    first_dates = []
    for c in _ADJ_COLS:
        sub = adj_tbl.loc[adj_tbl[c].notna() & (adj_tbl[c] > 0), "filing_date"]
        if not sub.empty:
            first_dates.append(sub.min())
    start = min(first_dates) - pd.DateOffset(years=5)
    t_end = max(adj_tbl["filing_date"].max(), pd.Timestamp.today().normalize()) + pd.Timedelta(days=14)

    try:
        import FinanceDataReader as fdr
    except ImportError:
        meta["per_error"] = "FinanceDataReader 미설치 — pip install finance-datareader"
        for row in series:
            clear_per_price_fields(row)
        return

    try:
        raw = fdr.DataReader(code, start=start, end=t_end)
    except Exception as exc:
        meta["per_error"] = f"주가 조회 실패 ({code}): {exc}"
        for row in series:
            clear_per_price_fields(row)
        return

    if raw is None or raw.empty:
        meta["per_error"] = f"주가 데이터 없음: {code}"
        for row in series:
            clear_per_price_fields(row)
        return

    px = raw.reset_index()
    date_col = "Date" if "Date" in px.columns else px.columns[0]
    px = px.rename(columns={date_col: "Date"})
    if "Close" not in px.columns:
        meta["per_error"] = "주가 컬럼 Close 없음"
        for row in series:
            clear_per_price_fields(row)
        return

    px["Date"] = pd.to_datetime(px["Date"]).dt.normalize()
    px = px.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")

    m_eps = _merge_price_ratio(px, adj_tbl, "EPS_adj")
    m_rev = _merge_price_ratio(px, adj_tbl, "Rev_adj")
    m_op = _merge_price_ratio(px, adj_tbl, "Op_adj")

    term_maps = {
        "eps": dict(zip(adj_tbl["term"], adj_tbl["EPS_adj"])),
        "rev": dict(zip(adj_tbl["term"], adj_tbl["Rev_adj"])),
        "op": dict(zip(adj_tbl["term"], adj_tbl["Op_adj"])),
    }
    term_to_filing = dict(zip(adj_tbl["term"], adj_tbl["filing_date"]))

    for row in series:
        clear_per_price_fields(row)
        te = row.get("ttm_end_term")
        if not te or row.get("error"):
            continue
        te = str(te)
        fd = term_to_filing.get(te)
        eps_adj = term_maps["eps"].get(te)
        rev_adj = term_maps["rev"].get(te)
        op_adj = term_maps["op"].get(te)

        if fd is not None:
            row["per_filing_anchor"] = fd.strftime("%Y-%m-%d")
        if eps_adj is not None and not (isinstance(eps_adj, float) and np.isnan(eps_adj)):
            row["per_eps_adjusted"] = float(eps_adj)

        today_n = pd.Timestamp.today().normalize()
        cap_d = min(pd.Timestamp(fd).normalize(), today_n) if fd is not None else today_n
        d_last = _last_trade_on_or_before(px, cap_d) if fd is not None else None
        if d_last is not None:
            hit = px.loc[px["Date"] == d_last, "Close"]
            if not hit.empty:
                row["per_anchor_close"] = float(hit.iloc[0])
                row["per_anchor_trade_date"] = d_last.strftime("%Y-%m-%d")

        _set_20d_4y(row, d_last, px, eps_adj, m_eps, "per_20d_mean", "per_4y_mean")
        _set_20d_4y(row, d_last, px, op_adj, m_op, "per_op_20d_mean", "per_op_4y_mean")
        _set_20d_4y(row, d_last, px, rev_adj, m_rev, "per_rev_20d_mean", "per_rev_4y_mean")

    meta["per_eps_basis"] = (
        "EPS 분모(지배순이익): FY 재무(11011) → 재무 롤4 TTM(양수만). "
        "매출·영업은 4Q FY(재무) → 롤4. 액면 보정은 eps_fps 와 동일. "
        "앵커일=1Q 5/15·2Q 8/15·3Q 11/15·4Q 익년 3/31."
    )
    meta["per_price_source"] = f"FinanceDataReader KRX {code} (수정주가)"
    meta.pop("per_error", None)


def clear_per_price_fields(row: dict[str, Any]) -> None:
    """주가·배수 관련 필드 제거 (스킵 시 populate 에서도 사용)."""
    for k in (
        "per_20d_mean",
        "per_4y_mean",
        "per_op_20d_mean",
        "per_op_4y_mean",
        "per_gp_20d_mean",
        "per_gp_4y_mean",
        "per_rev_20d_mean",
        "per_rev_4y_mean",
    ):
        row[k] = None
    row.pop("per_filing_anchor", None)
    row.pop("per_eps_adjusted", None)
    row.pop("per_anchor_close", None)
    row.pop("per_anchor_trade_date", None)


# 하위 호환 (기존 비공개 이름)
_clear_per_fields = clear_per_price_fields
