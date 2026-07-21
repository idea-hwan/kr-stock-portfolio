"""
주당 이익·CFO·Capex (유형+무형 취득) 4분기 누적(TTM).

CFO·Capex·FCF 주당은 루트 `eps_fps_growth_stock.py` 와 **동일 레일**:
  분기 현금흐름 Q → QFCFPS = Q / STOCKS, (QFCFPS/FaceValue) = Q / (STOCKS×FaceValue),
  TTM 주당(원) = rolling 4Q 합(Q/(STOCKS×FaceValue)) × **끝 분기 FaceValue**.

- STOCKS: `istc_totqy` — 보통주 행 우선(fs_metrics._load_istc_totqy), 결측 `bfill`→`ffill`
- FaceValue: 배당 DB 주당액면 행(레이블 여러 후보), 결측 `bfill`→`ffill`. **유효 액면(thstrm>0)을 끝까지 못 잡으면 ValueError** (하드코딩 폴백 없음).
→ 액면분할·주식수 변동 시에도 총액·주식·액면 곱 구조와 맞춤.

손익 TTM·FY·PER 분모: **매출·영업이익·지배순이익**만(매출총이익은 TTM 레일에서 제외). 배당·분배는 별도 파이프라인.

분할 직전·직후 TTM은 “원/주” 숫자 스케일이 달라질 수 있음(같은 회사 현금인데 주 1주 정의가 다름).
장기 성장은 `eps_fps` 처럼 FaceValue 로 한 번 더 나눈 축·로그 성장 등 기존 스크립트와 맞출 것.

손익 FY: 사업보고(11011) 당기 ÷ 끝 분기 istc (기존과 동일).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.analysis import fs_metrics as fm
from scripts.analysis.series_per import enrich_ttm_series_with_per
from scripts.quarter_terms import iter_terms, parse_term, shift_term
from scripts.stock_db import DIVIDEND_DB_DIR

# TTM 손익 롤4·FY: 매출총이익은 공시·업종 편차로 결측이 많아 제외 (fs_metrics 의 gross_profit 은 유지)
PL_KEYS = ("revenue", "operating_income", "net_income_parent")

_FACE_VALUE_SE_EXACT: tuple[str, ...] = (
    "주당액면가액(원)",
    "주당액면금액(원)",
    "주당액면가격(원)",
    "액면가액(원)",
    "주당액면가(원)",
)


def _load_face_value(db: fm.FS_DB, term: str, company: str) -> int | None:
    """배당 DB에서 주당 액면가(원). se 레이블·공백 편차 대응, 없으면 None."""
    try:
        dfd = db.read_dividend_db(term, company)
    except Exception:
        return None
    if dfd is None or dfd.empty or "se" not in dfd.columns:
        return None
    amt_col = "thstrm" if "thstrm" in dfd.columns else None
    if not amt_col:
        return None
    se = dfd["se"].astype(str).str.strip()
    for lab in _FACE_VALUE_SE_EXACT:
        m = dfd.loc[se == lab]
        if not m.empty:
            v = fm._parse_amount(m.iloc[0].get(amt_col))
            if v is not None and v > 0:
                return v
    # "주당…액면…" 형태만 맞는 비표준 레이블
    loose = se.str.contains("주당", na=False) & se.str.contains("액면", na=False)
    m = dfd.loc[loose]
    if not m.empty:
        v = fm._parse_amount(m.iloc[0].get(amt_col))
        if v is not None and v > 0:
            return v
    return None


def _panel(db: fm.FS_DB, company: str, chrono: list[str]) -> pd.DataFrame:
    rows = []
    for t in chrono:
        st = fm._load_istc_totqy(t, company)
        fv = _load_face_value(db, t, company)
        df = fm._load_fs_or_empty(db, t, company)
        if df.empty:
            rows.append({"term": t, "istc": st, "face_value": fv})
            continue
        row: dict[str, Any] = {
            "term": t,
            "istc": st,
            "face_value": fv,
            "reprt": fm._reprt_code(df),
        }
        for k in PL_KEYS:
            row[k] = fm._pick_from_df(df, k)
        row["cfo"] = fm._pick_from_df(df, "cfo")
        ppe = fm._pick_from_df(df, "ppe_capex")
        ia = fm._pick_from_df(df, "ia_capex")
        row["capex_cum"] = None
        if row["cfo"] is not None or ppe is not None or ia is not None:
            row["capex_cum"] = (ppe or 0) + (ia or 0)
        rows.append(row)
    out = pd.DataFrame(rows)
    # eps_fps_growth_stock: FaceValue bfill → ffill, STOCKS 동일
    fv = pd.to_numeric(out["face_value"], errors="coerce")
    out["FaceValue"] = fv.bfill().ffill()
    if out["FaceValue"].isna().any():
        bad_terms = out.loc[out["FaceValue"].isna(), "term"].astype(str).tolist()
        raise ValueError(
            f"[{company}] 배당 DB에서 유효한 주당 액면가(원)를 확정하지 못했습니다 "
            f"(bfill→ffill 후에도 결측인 분기: {bad_terms}). "
            "se=주당액면가액(원) 등의 thstrm이 0이 아닌 양수인지, 배당 분기 DB를 확인하세요."
        )
    iv = pd.to_numeric(out["istc"], errors="coerce")
    out["istc_ffill"] = iv.bfill().ffill()
    return out


def _ttm_per_share_eps_fps(
    sub: pd.DataFrame,
    qcol: str,
) -> float | None:
    """
    sum_{4Q}( Q / STOCKS / FaceValue ) * FaceValue_end — eps_fps 의 1Y_FCFPS 와 같은 식.
    """
    if len(sub) != 4:
        return None
    fv_end = sub.iloc[-1]["FaceValue"]
    if fv_end is None or pd.isna(fv_end) or float(fv_end) == 0:
        return None
    fv_end_f = float(fv_end)
    acc = 0.0
    for _, r in sub.iterrows():
        qv, st, fv = r[qcol], r["istc_ffill"], r["FaceValue"]
        if qv is None or pd.isna(qv) or st is None or pd.isna(st) or fv is None or pd.isna(fv):
            return None
        st_f, fv_f = float(st), float(fv)
        if st_f == 0 or fv_f == 0:
            return None
        acc += float(qv) / st_f / fv_f
    return acc * fv_end_f


def _add_quarterly_cum(panel: pd.DataFrame, col: str, out_col: str) -> None:
    vals = panel[col].tolist()
    terms = panel["term"].tolist()
    panel[out_col] = fm._quarterly_from_cumulative(terms, vals)  # type: ignore[arg-type]


def compute(
    anchor_term: str,
    company: str,
    history_q: int = 8,
) -> dict[str, Any]:
    db = fm.FS_DB()
    chrono = fm._terms_chronological(anchor_term, history_q)
    panel = _panel(db, company, chrono)

    anchor_df = fm._load_fs_or_empty(db, anchor_term, company)
    if anchor_df.empty:
        raise FileNotFoundError(f"앵커 재무 없음: {company} @ {anchor_term}")
    anchor_reprt = fm._reprt_code(anchor_df)
    istc_end = fm._load_istc_totqy(anchor_term, company)
    if istc_end is None or istc_end == 0:
        istc_end = int(panel["istc_ffill"].dropna().iloc[-1])

    for k in PL_KEYS:
        _add_quarterly_cum(panel, k, f"q_{k}")

    _add_quarterly_cum(panel, "cfo", "q_cfo")
    _add_quarterly_cum(panel, "capex_cum", "q_capex")

    last4 = panel.tail(4).copy()
    notes: list[str] = []

    def ttm_sum(col: str) -> int | None:
        s = last4[col].tolist()
        if len(s) < 4 or any(x is None for x in s):
            return None
        return int(sum(x for x in s if x is not None))  # type: ignore

    def ttm_ps_from_end(krw: int | None) -> float | None:
        if krw is None or istc_end == 0:
            return None
        return krw / istc_end

    roll_cfo = ttm_sum("q_cfo")
    roll_capex = ttm_sum("q_capex")
    bad_pl = []
    for k in PL_KEYS:
        qcol = f"q_{k}"
        if last4[qcol].notna().any():
            if (last4[qcol].dropna() < 0).any():
                bad_pl.append(k)

    income_fy_ps: dict[str, float | None] = {}
    if anchor_reprt == fm.REPRT_ANNUAL:
        for k in PL_KEYS:
            v = fm._pick_from_df(anchor_df, k)
            income_fy_ps[k] = v / istc_end if v is not None else None
        notes.append(
            "손익 TTM 주당: 사업보고 당기 ÷ 앵커 istc_totqy (반기·분기 누적 비단조 대응)."
        )
    else:
        for k in PL_KEYS:
            income_fy_ps[k] = None
        notes.append("앵커가 사업보고가 아니면 손익 FY 주당은 비움.")

    if bad_pl:
        notes.append(
            f"분기 차분 손익에 음수 구간 있음({', '.join(bad_pl)}) — 롤4 손익 합은 신뢰 낮음, FY 주당 사용 권장."
        )

    roll_pl_ps = {k: _ttm_per_share_eps_fps(last4, f"q_{k}") for k in PL_KEYS}

    cfo_eps = _ttm_per_share_eps_fps(last4, "q_cfo")
    capex_eps = _ttm_per_share_eps_fps(last4, "q_capex")
    fcf_eps = (
        cfo_eps - capex_eps
        if cfo_eps is not None and capex_eps is not None
        else None
    )

    result = {
        "meta": {
            "company": company,
            "anchor_term": anchor_term,
            "istc_totqy_anchor": istc_end,
            "face_value_anchor": float(last4.iloc[-1]["FaceValue"])
            if pd.notna(last4.iloc[-1]["FaceValue"])
            else None,
            "shares_note": (
                "STOCKS=istc_totqy, FaceValue=배당 DB 주당액면(다중 se)·bfill→ffill, "
                "액면 미확정 시 ValueError(폴백 없음)"
            ),
            "last_4_terms": last4["term"].tolist(),
        },
        "ttm_roll4_krw": {
            "cfo": roll_cfo,
            "capex": roll_capex,
            "fcf": roll_cfo - roll_capex if roll_cfo is not None and roll_capex is not None else None,
        },
        "ttm_roll4_per_share_won_end_istc": {
            "cfo": ttm_ps_from_end(roll_cfo),
            "capex": ttm_ps_from_end(roll_capex),
            "fcf": ttm_ps_from_end(
                roll_cfo - roll_capex
                if roll_cfo is not None and roll_capex is not None
                else None
            ),
        },
        "ttm_roll4_per_share_won_sum_quarters": {
            "cfo": cfo_eps,
            "capex": capex_eps,
            "fcf": fcf_eps,
        },
        "income_fy_per_share_won_istc_anchor": income_fy_ps,
        "roll4_pl_per_share_eps_fps": roll_pl_ps,
        "roll4_pl_per_share_won_end_istc_if_clean": roll_pl_ps,
        "quarterly_table": last4[
            ["term", "reprt", "istc", "istc_ffill", "FaceValue"]
            + [f"q_{k}" for k in PL_KEYS]
            + ["q_cfo", "q_capex"]
        ].to_dict(orient="records"),
        "notes": notes
        + [
            "TTM CFO·Capex·FCF/주: sum(Q/(STOCKS×FaceValue))×FaceValue_앵커 (= eps_fps 1Y_FCFPS 계열).",
        ],
    }

    return result


def _chrono_terms(start_t: str, end_t: str) -> list[str]:
    return [t for _, _, t in iter_terms(start_t, end_t)]


def _list_fs_db_terms() -> list[str]:
    """`data/financial_statement/*.db` 분기 파일명만 시간순."""
    out: list[str] = []
    for p in sorted(fm.FINANCIAL_DB_DIR.glob("*.db")):
        if re.fullmatch(r"\d{4}Q[1-4]", p.stem):
            out.append(p.stem)
    return out


def _list_dividend_db_terms() -> list[str]:
    """`data/dividend/*.db` 분기 파일명만 시간순."""
    out: list[str] = []
    for p in sorted(DIVIDEND_DB_DIR.glob("*.db")):
        if re.fullmatch(r"\d{4}Q[1-4]", p.stem):
            out.append(p.stem)
    return out


def _earliest_term_with_fs(company: str) -> str | None:
    db = fm.FS_DB()
    for t in _list_fs_db_terms():
        if not fm._load_fs_or_empty(db, t, company).empty:
            return t
    return None


def _earliest_term_with_dividend(company: str) -> str | None:
    """재무가 없어도 배당 DB에 행이 있으면 그 최초 분기(예: 금융지주 과거 공시)."""
    db = fm.FS_DB()
    for t in _list_dividend_db_terms():
        try:
            dfd = db.read_dividend_db(t, company)
            if dfd is not None and not dfd.empty:
                return t
        except Exception:
            continue
    return None


def infer_full_series_n_quarters(
    anchor_term: str, company: str
) -> tuple[int, str, str, str | None, str | None]:
    """
    **재무 DB**에 데이터가 있는 가장 이른 분기를 시작으로 연속 달력을 잡는다.
    첫 TTM 끝점 = 그 분기 + 3Q, 점 개수 = 그 끝점 ~ 앵커(포함).
    반환: (n_quarters, first_coverage_term, first_ttm_end, first_fs_term, first_dividend_term_or_none)
    마지막 값은 메타 참고용(시리즈 길이에는 미사용).
    """
    first_fs = _earliest_term_with_fs(company)
    if first_fs is None:
        raise FileNotFoundError(f"재무 DB에 {company} 데이터가 없습니다.")
    first_cov = first_fs
    first_div = _earliest_term_with_dividend(company)
    first_end = shift_term(first_cov, 3)
    ae, aq = parse_term(anchor_term)
    fe, fq = parse_term(first_end)
    if (fe, fq) > (ae, aq):
        raise ValueError(
            f"앵커 {anchor_term} 이(가) 첫 TTM 끝 가능 시점 {first_end} 보다 이전입니다."
        )
    n = sum(1 for _ in iter_terms(first_end, anchor_term))
    return n, first_cov, first_end, first_fs, first_div


def compute_ttm_series(
    anchor_term: str,
    company: str,
    n_quarters: int = 32,
) -> dict[str, Any]:
    """
    앵커 분기를 끝으로 하는 TTM(4Q) 주당 시계열 n_quarters 개 (기본 32 = 8년).
    가장 오래된 끝점은 shift(anchor, -(n-1)).
    """
    if n_quarters < 1:
        raise ValueError("n_quarters >= 1")

    oldest_end = shift_term(anchor_term, -(n_quarters - 1))
    min_term = shift_term(oldest_end, -4)
    chrono = _chrono_terms(min_term, anchor_term)

    db = fm.FS_DB()
    panel = _panel(db, company, chrono).reset_index(drop=True)
    # istc_ffill 은 _panel 에서 istc_adj 반영 후 이미 계산됨 (여기서 덮어쓰지 말 것)

    for k in PL_KEYS:
        _add_quarterly_cum(panel, k, f"q_{k}")
    _add_quarterly_cum(panel, "cfo", "q_cfo")
    _add_quarterly_cum(panel, "capex_cum", "q_capex")

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
            sub = panel_idx.loc[w].copy()
        except KeyError:
            rows_out.append({"ttm_end_term": end_t, "error": "missing_term_in_panel"})
            continue
        sub = sub.reset_index()

        def ttm_sum_q(col: str) -> int | None:
            s = sub[col].tolist()
            if len(s) != 4 or any(x is None or (isinstance(x, float) and pd.isna(x)) for x in s):
                return None
            return int(sum(int(x) for x in s))

        roll_cfo = ttm_sum_q("q_cfo")
        roll_capex = ttm_sum_q("q_capex")
        istc_end = sub.iloc[-1]["istc_ffill"]
        if istc_end is None or pd.isna(istc_end) or istc_end == 0:
            istc_end_f = None
        else:
            istc_end_f = float(istc_end)

        bad_pl = []
        for k in PL_KEYS:
            qc = f"q_{k}"
            if sub[qc].notna().any() and (sub[qc].dropna() < 0).any():
                bad_pl.append(k)

        income_fy_ps: dict[str, float | None] = {k: None for k in PL_KEYS}
        income_src = None
        end_df = fm._load_fs_or_empty(db, end_t, company)
        qn = int(end_t.split("Q")[1])
        if (
            not end_df.empty
            and fm._reprt_code(end_df) == fm.REPRT_ANNUAL
            and qn == 4
            and istc_end_f
        ):
            income_src = "fy_11011"
            for k in PL_KEYS:
                v = fm._pick_from_df(end_df, k)
                income_fy_ps[k] = v / istc_end_f if v is not None else None

        roll_pl_ps = {k: _ttm_per_share_eps_fps(sub, f"q_{k}") for k in PL_KEYS}

        cfo_ps = _ttm_per_share_eps_fps(sub, "q_cfo")
        capex_ps = _ttm_per_share_eps_fps(sub, "q_capex")
        fcf_ps = (
            cfo_ps - capex_ps
            if cfo_ps is not None and capex_ps is not None
            else None
        )

        fv_end = (
            float(sub.iloc[-1]["FaceValue"])
            if pd.notna(sub.iloc[-1]["FaceValue"])
            else None
        )

        row: dict[str, Any] = {
            "ttm_end_term": end_t,
            "window_terms": w,
            "ttm_krw": {
                "cfo": roll_cfo,
                "capex": roll_capex,
                "fcf": roll_cfo - roll_capex
                if roll_cfo is not None and roll_capex is not None
                else None,
            },
            "ttm_per_share_won_sum_quarters": {
                "cfo": cfo_ps,
                "capex": capex_ps,
                "fcf": fcf_ps,
            },
            "income_per_share_won_fy_if_q4_annual": income_fy_ps,
            "income_source": income_src,
            "roll4_pl_per_share_eps_fps": roll_pl_ps,
            "roll4_pl_per_share_won_end_istc": roll_pl_ps,
            "pl_roll4_dirty": bad_pl if bad_pl else None,
            "istc_ffill_at_end": istc_end_f,
            "face_value_at_end": fv_end,
        }

        rows_out.append(row)

    return {
        "meta": {
            "company": company,
            "anchor_term": anchor_term,
            "n_points": n_quarters,
            "oldest_ttm_end": shift_term(anchor_term, -(n_quarters - 1)),
            "data_range_loaded": [min_term, anchor_term],
            "note": (
                "CFO·Capex·FCF/주 = sum(Q/(STOCKS×FaceValue))×FaceValue_끝분기 (eps_fps). "
                "FaceValue=배당 주당액면(여러 레이블)·bfill→ffill, 미확정 시 ValueError. "
                "손익/주·PER 분모: 재무 FY(11011) 또는 재무 롤4만."
            ),
        },
        "series": rows_out,
    }


def _series_result_to_dataframe(r: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in r["series"]:
        te = row.get("ttm_end_term", "")
        if row.get("error"):
            rows.append(
                {
                    "ttm_end": te,
                    "error": row["error"],
                    "PER_공시앵커": "",
                    "PER_앵커거래일": "",
                    "PER_앵커종가": None,
                    "PER_20d평균": None,
                    "PER_4y평균": None,
                    "P_OP_20d": None,
                    "P_OP_4y": None,
                    "P_Rev_20d": None,
                    "P_Rev_4y": None,
                }
            )
            continue
        ps = row.get("ttm_per_share_won_sum_quarters") or {}
        fy = row.get("income_per_share_won_fy_if_q4_annual") or {}
        pl = row.get("roll4_pl_per_share_eps_fps") or {}
        rec: dict[str, Any] = {
            "ttm_end": te,
            "CFO/주": ps.get("cfo"),
            "Capex/주": ps.get("capex"),
            "FCF/주": ps.get("fcf"),
            "FY구분": row.get("income_source") or "",
            "액면(끝)": row.get("face_value_at_end"),
            "istc_ffill(끝)": row.get("istc_ffill_at_end"),
        }
        for k in PL_KEYS:
            rec[k] = pl.get(k)
        for k in PL_KEYS:
            rec[f"FY_{k}"] = fy.get(k)
        dirty = row.get("pl_roll4_dirty")
        rec["pl_dirty"] = ",".join(dirty) if dirty else ""
        rec["PER_공시앵커"] = row.get("per_filing_anchor") or ""
        rec["PER_앵커거래일"] = row.get("per_anchor_trade_date") or ""
        rec["PER_앵커종가"] = row.get("per_anchor_close")
        rec["PER_20d평균"] = row.get("per_20d_mean")
        rec["PER_4y평균"] = row.get("per_4y_mean")
        rec["P_OP_20d"] = row.get("per_op_20d_mean")
        rec["P_OP_4y"] = row.get("per_op_4y_mean")
        rec["P_Rev_20d"] = row.get("per_rev_20d_mean")
        rec["P_Rev_4y"] = row.get("per_rev_4y_mean")
        rows.append(rec)
    _per_tail = [
        "PER_공시앵커",
        "PER_앵커거래일",
        "PER_앵커종가",
        "PER_20d평균",
        "PER_4y평균",
        "P_OP_20d",
        "P_OP_4y",
        "P_Rev_20d",
        "P_Rev_4y",
    ]
    cols = (
        ["ttm_end", "CFO/주", "Capex/주", "FCF/주"]
        + list(PL_KEYS)
        + [f"FY_{k}" for k in PL_KEYS]
        + [
            "FY구분",
            "액면(끝)",
            "istc_ffill(끝)",
            "pl_dirty",
        ]
        + _per_tail
    )
    df = pd.DataFrame(rows)
    ordered = [c for c in cols if c in df.columns]
    if "error" in df.columns and "error" not in ordered:
        ordered.append("error")
    return df[ordered]


def _fmt_ps_cell(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    try:
        return f"{float(x):,.2f}"
    except (TypeError, ValueError):
        return str(x)


def _fmt_intish_cell(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    try:
        return f"{int(round(float(x))):,}"
    except (TypeError, ValueError):
        return str(x)


def _fmt_ps_rjust(x: Any, width: int = 13) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "".rjust(width)
    try:
        return f"{float(x):>{width},.2f}"
    except (TypeError, ValueError):
        return str(x)[:width].rjust(width)


def _fmt_istc_short(x: Any) -> str:
    """백만 주 단위로 짧게 (가독성)."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    try:
        m = float(x) / 1_000_000.0
        return f"{m:,.2f}M"
    except (TypeError, ValueError):
        return str(x)


def _dirty_short(s: str, max_len: int = 22) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _block_to_string(df: pd.DataFrame, formatters: dict[str, Any]) -> str:
    with pd.option_context(
        "display.max_rows",
        500,
        "display.width",
        200,
        "display.max_columns",
        None,
    ):
        return df.to_string(index=False, formatters=formatters, na_rep="—")


def _fmt_eok_rjust(x: Any, width: int = 12) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "".rjust(width)
    try:
        return f"{float(x):>{width},.2f}"
    except (TypeError, ValueError):
        return str(x)[:width].rjust(width)


def _series_ttm_krw_block(r: dict[str, Any]) -> pd.DataFrame:
    """compute_ttm_series 의 ttm_krw(원) → 억원 표시용."""

    def div1e8(v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(v) / 1e8
        except (TypeError, ValueError):
            return None

    rows: list[dict[str, Any]] = []
    for row in r.get("series") or []:
        te = str(row.get("ttm_end_term", "")).strip()
        if row.get("error"):
            rows.append({"ttm_end": te, "cfo_eok": None, "capex_eok": None, "fcf_eok": None})
            continue
        tk = row.get("ttm_krw") or {}
        rows.append(
            {
                "ttm_end": te,
                "cfo_eok": div1e8(tk.get("cfo")),
                "capex_eok": div1e8(tk.get("capex")),
                "fcf_eok": div1e8(tk.get("fcf")),
            }
        )
    return pd.DataFrame(rows)


def _numeric_na_count(s: pd.Series) -> int:
    return int(pd.to_numeric(s, errors="coerce").isna().sum())


def _blank_per_series_to_na(s: pd.Series) -> pd.Series:
    s = s.astype(object)
    empty = s.isna() | (s.astype(str).str.strip() == "") | (s.astype(str).str.strip() == "nan")
    return s.mask(empty, pd.NA)


def _series_master_dataframe(r: dict[str, Any]) -> pd.DataFrame:
    """Full TTM series as one DataFrame (English column names)."""
    df = _series_result_to_dataframe(r).reset_index(drop=True)
    if df.empty:
        return df
    d1k = _series_ttm_krw_block(r).reset_index(drop=True)
    n = len(df)
    pl_raw = df["pl_dirty"].fillna("").astype(str).str.strip()
    dirty_disp = pl_raw.map(lambda s: _dirty_short(s, max_len=40) if s else "")
    dirty_out = dirty_disp.mask(dirty_disp == "", pd.NA)

    fy_src = df["FY구분"] if "FY구분" in df.columns else pd.Series([pd.NA] * n)
    fy_src = fy_src.astype(object).where(
        fy_src.notna() & (fy_src.astype(str).str.strip() != ""), pd.NA
    )

    def per_col(name: str) -> pd.Series:
        if name not in df.columns:
            return pd.Series([pd.NA] * n)
        return _blank_per_series_to_na(df[name])

    out = pd.DataFrame(
        {
            "ttm_end": df["ttm_end"].astype(str).str.strip(),
            "cfo_ps": df["CFO/주"],
            "capex_ps": df["Capex/주"],
            "fcf_ps": df["FCF/주"],
            "cfo_eok": d1k["cfo_eok"],
            "capex_eok": d1k["capex_eok"],
            "fcf_eok": d1k["fcf_eok"],
            "rev_roll4_ps": df["revenue"],
            "op_roll4_ps": df["operating_income"],
            "ni_roll4_ps": df["net_income_parent"],
            "fy_rev_ps": df["FY_revenue"],
            "fy_op_ps": df["FY_operating_income"],
            "fy_ni_ps": df["FY_net_income_parent"],
            "fy_src": fy_src,
            "face_value": df["액면(끝)"],
            "istc_m": df["istc_ffill(끝)"],
            "pl_dirty": dirty_out,
            "per_filing_anchor": per_col("PER_공시앵커"),
            "per_trade_date": per_col("PER_앵커거래일"),
            "per_anchor_close": df["PER_앵커종가"] if "PER_앵커종가" in df.columns else pd.Series([pd.NA] * n),
            "per_20d": df["PER_20d평균"] if "PER_20d평균" in df.columns else pd.Series([pd.NA] * n),
            "per_4y": df["PER_4y평균"] if "PER_4y평균" in df.columns else pd.Series([pd.NA] * n),
            "p_op_20d": df["P_OP_20d"] if "P_OP_20d" in df.columns else pd.Series([pd.NA] * n),
            "p_op_4y": df["P_OP_4y"] if "P_OP_4y" in df.columns else pd.Series([pd.NA] * n),
            "p_rev_20d": df["P_Rev_20d"] if "P_Rev_20d" in df.columns else pd.Series([pd.NA] * n),
            "p_rev_4y": df["P_Rev_4y"] if "P_Rev_4y" in df.columns else pd.Series([pd.NA] * n),
        }
    )
    if "error" in df.columns:
        em = df["error"]
        if em.notna().any() and (em.astype(str).str.strip() != "").any():
            out["error"] = em
    return out


def _fmt_wide_ps(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    try:
        return f"{float(x):,.2f}"
    except (TypeError, ValueError):
        return str(x)


def _fmt_wide_eok(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    try:
        return f"{float(x):,.2f}"
    except (TypeError, ValueError):
        return str(x)


def _fmt_wide_int(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    try:
        return f"{int(round(float(x))):,}"
    except (TypeError, ValueError):
        return str(x)


def _fmt_wide_per(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    try:
        return f"{float(x):,.2f}"
    except (TypeError, ValueError):
        return str(x)


def _fmt_wide_str(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    s = str(x).strip()
    return s if s else "—"


def print_series_wide(r: dict[str, Any]) -> None:
    """Wide single table (default CLI output)."""
    base = _series_result_to_dataframe(r).reset_index(drop=True)
    wide = _series_master_dataframe(r)
    if wide.empty:
        print("(no series rows)")
        return

    n = len(wide)
    n_fy_ni = 0
    if "fy_ni_ps" in wide.columns:
        n_fy_ni = int(pd.to_numeric(wide["fy_ni_ps"], errors="coerce").notna().sum())
    pl_raw = base["pl_dirty"].fillna("").astype(str).str.strip()
    n_dirty = int((pl_raw.str.len() > 0).sum())

    print()
    print(
        f"Summary: {n} TTM ends | cfo_ps missing {_numeric_na_count(base['CFO/주'])} · "
        f"rev_roll4 missing {_numeric_na_count(base['revenue'])} | "
        f"FY ni_ps filled {n_fy_ni} rows (Q4·11011) | pl_dirty tags {n_dirty} rows"
    )
    print(
        "  — is missing. Non-empty pl_dirty: roll4 P/L is indicative (negative q/q diffs in window)."
    )
    print()

    fmt_map: dict[str, Any] = {
        "cfo_ps": _fmt_wide_ps,
        "capex_ps": _fmt_wide_ps,
        "fcf_ps": _fmt_wide_ps,
        "cfo_eok": _fmt_wide_eok,
        "capex_eok": _fmt_wide_eok,
        "fcf_eok": _fmt_wide_eok,
        "rev_roll4_ps": _fmt_wide_ps,
        "op_roll4_ps": _fmt_wide_ps,
        "ni_roll4_ps": _fmt_wide_ps,
        "fy_rev_ps": _fmt_wide_ps,
        "fy_op_ps": _fmt_wide_ps,
        "fy_ni_ps": _fmt_wide_ps,
        "fy_src": _fmt_wide_str,
        "face_value": _fmt_wide_int,
        "istc_m": lambda x: _fmt_istc_short(x) or "—",
        "pl_dirty": _fmt_wide_str,
        "per_filing_anchor": _fmt_wide_str,
        "per_trade_date": _fmt_wide_str,
        "per_anchor_close": _fmt_wide_int,
        "per_20d": _fmt_wide_per,
        "per_4y": _fmt_wide_per,
        "p_op_20d": _fmt_wide_per,
        "p_op_4y": _fmt_wide_per,
        "p_rev_20d": _fmt_wide_per,
        "p_rev_4y": _fmt_wide_per,
        "error": _fmt_wide_str,
    }
    use_fmt = {c: fmt_map[c] for c in wide.columns if c in fmt_map}
    disp = wide.copy()
    for c, fn in use_fmt.items():
        disp[c] = disp[c].map(fn)
    disp = disp.astype(str).replace(
        {"<NA>": "—", "nan": "—", "NaT": "—", "None": "—", "": "—"}
    )
    with pd.option_context(
        "display.max_rows",
        500,
        "display.max_columns",
        None,
        "display.width",
        400,
        "display.unicode.east_asian_width",
        True,
    ):
        print(disp.to_string(index=False, na_rep="—"))
    per_err = (r.get("meta") or {}).get("per_error")
    if per_err:
        print(f"\nPER note: {per_err}")
    if "error" in wide.columns:
        sub = wide[wide["error"].notna() & (wide["error"].astype(str).str.strip() != "")]
        sub = sub[sub["error"].astype(str) != "—"]
        if not sub.empty:
            print("\n[errors]")
            print(
                sub[["ttm_end", "error"]]
                .to_string(index=False, formatters={"error": _fmt_wide_str}, na_rep="—")
            )
    print(
        "\nPrice / sh: TTM roll4 (NI·OP·Rev); same face-value adj & filing anchors; "
        "20d/4y columns = 주가 ÷ 보정 주당."
    )


def print_series_blocks(r: dict[str, Any]) -> None:
    """Sectioned tables (--series-layout blocks)."""
    df = _series_result_to_dataframe(r).reset_index(drop=True)
    if df.empty:
        print("(no series rows)")
        return

    ttm = df["ttm_end"].astype(str).str.strip()
    w = 13
    we = 12

    def fj(x: Any, _w: int = w) -> str:
        return _fmt_ps_rjust(x, _w)

    def fe(x: Any, _w: int = we) -> str:
        return _fmt_eok_rjust(x, _w)

    n = len(df)
    n_fy_ni = 0
    if "FY_net_income_parent" in df.columns:
        n_fy_ni = int(pd.to_numeric(df["FY_net_income_parent"], errors="coerce").notna().sum())

    pl_raw = df["pl_dirty"].fillna("").astype(str).str.strip()
    dirty_mask = pl_raw.str.len() > 0
    sub_dirty = df.loc[dirty_mask, ["ttm_end", "pl_dirty"]].copy()
    sub_dirty["ttm_end"] = sub_dirty["ttm_end"].astype(str).str.strip()
    sub_dirty["pl_roll4_tags"] = sub_dirty["pl_dirty"].astype(str).str.strip().map(
        lambda s: _dirty_short(s, max_len=52)
    )
    sub_dirty = sub_dirty[sub_dirty["pl_roll4_tags"].str.len() > 0][
        ["ttm_end", "pl_roll4_tags"]
    ]
    n_dirty_print = len(sub_dirty)

    print()
    print(
        f"Summary: {n} TTM ends | [1] cfo_ps missing {_numeric_na_count(df['CFO/주'])} · "
        f"rev_roll4 missing {_numeric_na_count(df['revenue'])} | "
        f"[3] FY ni rows {n_fy_ni} (Q4·11011) | [2-x] pl_dirty rows {n_dirty_print}"
    )
    print("  — means missing (DB / cum / diff rules), not omitted output.")
    print(
        "  — on revenue roll4 only but other P/L present: some quarter missing revenue in window."
    )
    print()

    print("[1] Cash flow TTM / sh (KRW)")
    d1 = pd.DataFrame(
        {
            "ttm_end": ttm,
            "cfo_ps": df["CFO/주"],
            "capex_ps": df["Capex/주"],
            "fcf_ps": df["FCF/주"],
        }
    )
    print(_block_to_string(d1, {"cfo_ps": fj, "capex_ps": fj, "fcf_ps": fj}))
    print()

    print("[1-x] Same TTM cash totals (sum of 4Q diffs, KRW 100m) — before sh scaling")
    d1k = _series_ttm_krw_block(r)
    print(
        _block_to_string(
            d1k,
            {"cfo_eok": fe, "capex_eok": fe, "fcf_eok": fe},
        )
    )
    print()

    print("[2] P/L TTM roll4 / sh (KRW) — sum of 4 quarterly P/L diffs (매출·영업·지배순이익)")
    d2 = pd.DataFrame(
        {
            "ttm_end": ttm,
            "rev_ps": df["revenue"],
            "op_ps": df["operating_income"],
            "ni_ps": df["net_income_parent"],
        }
    )
    print(_block_to_string(d2, {"rev_ps": fj, "op_ps": fj, "ni_ps": fj}))

    if n_dirty_print > 0:
        print()
        print("[2-x] Negative q/q diff in window — roll4 P/L indicative (tags)")
        print(sub_dirty.to_string(index=False, na_rep="—"))
    print()

    print("[3] P/L FY / sh (KRW) — Q4 annual 11011 only")
    fy_map = {
        "fy_rev_ps": "FY_revenue",
        "fy_op_ps": "FY_operating_income",
        "fy_ni_ps": "FY_net_income_parent",
    }
    d3 = pd.DataFrame({"ttm_end": ttm})
    for disp, src in fy_map.items():
        d3[disp] = df[src] if src in df.columns else None
    if "FY구분" in df.columns:
        d3["fy_src"] = df["FY구분"].fillna("").astype(str)
    else:
        d3["fy_src"] = pd.Series([""] * len(df), dtype=object)
    fcols = [c for c in d3.columns if c.startswith("fy_") and c != "fy_src"]
    fmt3 = {c: fj for c in fcols}
    print(_block_to_string(d3, fmt3))
    print()

    print("[4] Scale — face value (KRW), istc_ffill (million sh)")
    d4 = pd.DataFrame(
        {
            "ttm_end": ttm,
            "face_value": df["액면(끝)"],
            "istc_m": df["istc_ffill(끝)"],
        }
    )
    print(
        _block_to_string(
            d4,
            {
                "face_value": _fmt_intish_cell,
                "istc_m": _fmt_istc_short,
            },
        )
    )
    print()

    print(
        "[5] Price ÷ TTM/sh (NI·OP·Rev, roll4); filing Q1 5/15, Q2 8/15, Q3 11/15, Q4+1 3/31; "
        "anchor close = last trade on/before min(filing,today); "
        "20d = mean(close 20d)/보정주당; 4y = mean daily (close÷보정주당) over 4y to anchor"
    )
    d5 = pd.DataFrame(
        {
            "ttm_end": ttm,
            "per_filing_anchor": df["PER_공시앵커"] if "PER_공시앵커" in df.columns else "",
            "per_trade_date": df["PER_앵커거래일"] if "PER_앵커거래일" in df.columns else "",
            "per_anchor_close": df["PER_앵커종가"] if "PER_앵커종가" in df.columns else None,
            "per_20d": df["PER_20d평균"] if "PER_20d평균" in df.columns else None,
            "per_4y": df["PER_4y평균"] if "PER_4y평균" in df.columns else None,
            "p_op_20d": df["P_OP_20d"] if "P_OP_20d" in df.columns else None,
            "p_op_4y": df["P_OP_4y"] if "P_OP_4y" in df.columns else None,
            "p_rev_20d": df["P_Rev_20d"] if "P_Rev_20d" in df.columns else None,
            "p_rev_4y": df["P_Rev_4y"] if "P_Rev_4y" in df.columns else None,
        }
    )
    def fp(x: Any, _w: int = 10) -> str:
        return _fmt_ps_rjust(x, _w)

    print(
        _block_to_string(
            d5,
            {
                "per_anchor_close": _fmt_intish_cell,
                "per_20d": fp,
                "per_4y": fp,
                "p_op_20d": fp,
                "p_op_4y": fp,
                "p_rev_20d": fp,
                "p_rev_4y": fp,
            },
        )
    )
    per_err = (r.get("meta") or {}).get("per_error")
    if per_err:
        print(f"  PER skipped/failed: {per_err}")

    if "error" in df.columns and df["error"].astype(str).str.len().gt(0).any():
        print()
        print("[errors]")
        print(df.loc[df["error"].notna() & (df["error"] != ""), ["ttm_end", "error"]].to_string(index=False))

    print()
    print("Note: rows with [2-x] tags — distrust roll4 P/L; prefer [3] FY / filings.")


def print_series_dataframe(r: dict[str, Any], *, layout: str = "wide") -> None:
    if layout == "blocks":
        print_series_blocks(r)
    else:
        print_series_wide(r)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="이익·CFO·Capex 주당 4Q 누적 (eps_fps 스타일)")
    p.add_argument("--company", default="삼성전자")
    p.add_argument("--term", default="2025Q4")
    p.add_argument(
        "--series",
        type=str,
        default=None,
        metavar="N|full",
        help="TTM 주당 시계열: 정수 N(점 개수) 또는 full=DB상 최초 FS~앵커 전 구간",
    )
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--no-per",
        action="store_true",
        help="시계열 모드에서 주가·PER(20일·4년) 조회 생략 (네트워크 미사용)",
    )
    p.add_argument(
        "--series-layout",
        choices=("wide", "blocks"),
        default="wide",
        metavar="LAYOUT",
        help="시계열 텍스트 출력: wide=한 표(기본), blocks=섹션별 다중 표",
    )
    args = p.parse_args(argv)

    if args.series is not None:
        try:
            s = args.series.strip().lower()
            if s == "full":
                n_q, first_cov, first_end, first_fs, first_div = (
                    infer_full_series_n_quarters(args.term, args.company)
                )
                r = compute_ttm_series(args.term, args.company, n_quarters=n_q)
                r["meta"]["series_mode"] = "full"
                r["meta"]["first_coverage_term"] = first_cov
                r["meta"]["first_fs_term"] = first_fs
                r["meta"]["first_dividend_term"] = first_div
                r["meta"]["first_ttm_end_inferred"] = first_end
            else:
                n_q = int(args.series)
                r = compute_ttm_series(args.term, args.company, n_quarters=n_q)
        except (FileNotFoundError, ValueError) as e:
            print(str(e), file=sys.stderr)
            return 1
        if not args.no_per:
            enrich_ttm_series_with_per(r, args.company)
        elif "meta" in r:
            r["meta"]["per_skipped"] = "--no-per"
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
            return 0
        m = r["meta"]
        print(
            f"company: {m['company']}  anchor: {m['anchor_term']}  series_points: {m['n_points']}"
        )
        print(f"data_range: {m['data_range_loaded'][0]} ~ {m['data_range_loaded'][1]}")
        print(f"oldest_ttm_end: {m['oldest_ttm_end']}")
        if m.get("series_mode") == "full":
            print(
                f"full: first_coverage {m['first_coverage_term']} → "
                f"first_ttm_end {m['first_ttm_end_inferred']}  "
                f"(FS {m.get('first_fs_term')}, div {m.get('first_dividend_term')})"
            )
        print()
        print_series_dataframe(r, layout=args.series_layout)
        return 0

    try:
        r = compute(args.term, args.company)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0

    m = r["meta"]
    print(f"회사: {m['company']}  앵커: {m['anchor_term']}")
    print(f"최근 4분기: {m['last_4_terms']}")
    print(f"istc_totqy(앵커): {m['istc_totqy_anchor']:,}")
    if m.get("face_value_anchor") is not None:
        print(f"FaceValue(앵커): {m['face_value_anchor']:,.0f}")
    print()

    print("=== TTM 원(4분기 차분 합, CFO·Capex만) ===")
    for k, v in r["ttm_roll4_krw"].items():
        print(f"  {k}: {v:,}" if isinstance(v, int) else f"  {k}: {v}")
    print()

    print("=== TTM 주당(원) — 4Q 합 ÷ 앵커 istc ===")
    for k, v in r["ttm_roll4_per_share_won_end_istc"].items():
        print(f"  {k}: {v:,.2f}" if v is not None else f"  {k}: —")
    print()

    print("=== TTM 주당(원) — eps_fps: sum(Q/(STOCKS×FaceValue))×FaceValue_앵커 ===")
    for k, v in r["ttm_roll4_per_share_won_sum_quarters"].items():
        print(f"  {k}: {v:,.2f}" if v is not None else f"  {k}: —")
    print()

    print("=== 손익 주당(원) — 사업보고 당기 ÷ 앵커 istc (권장) ===")
    for k, v in r["income_fy_per_share_won_istc_anchor"].items():
        print(f"  {k}: {v:,.2f}" if v is not None else f"  {k}: —")
    print()

    print("=== 분기별 (최근 4Q, 원) ===")
    for row in r["quarterly_table"]:
        print(row)

    if r["notes"]:
        print()
        for n in r["notes"]:
            print(f"  ※ {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
