"""
액면가 변화 없이 주식수만 바뀐 사건(무상증자·유상증자·소각 등) 감지와 무상증자 소급 보정.

배경: 주가(FDR)는 무상증자를 과거 전체에 소급 보정하지만, 과거 분기 주당 이익은
`이익/(주식수×액면가)`라서 그대로다 → 사건 이전 구간 PER 이 낮게 나온다(현대글로비스 2024 등).
액면분할은 액면가 체인(series_per)이 처리하므로 여기서는 **액면가가 같은** 사건만 본다.

분류 (해당 분기 재무제표의 증거):
  - 무상증자: 자본변동표 `dart_BonusIssue`/`무상증자`(자본금 증가)가 있고 유상증자 현금유입이 무상 금액의 20% 이하
              → 사건 이전 분기 주식수에 증가 배수를 곱해 최신 기준으로 소급 보정(adjusted=True)
  - 무상+유상: 둘 다 의미 있는 크기 → 섞여 있어 보정하지 않고 주석만 남김
  - 유상증자: 현금유입만 → 실제 희석이라 보정 안 함(주가도 대체로 보정되지 않음)
  - 감소: 비율 ≤ 0.8 (소각·감자·분할) → 보정 안 함, 주석만
  - 불명: 주식수·자본금은 변했지만 증거 항목이 없음 → 보정 안 함, 주석만
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from scripts.analysis import fs_metrics as fm

OVERRIDES_CSV = Path(__file__).resolve().parent.parent.parent / "stock_data" / "share_event_overrides.csv"
_overrides: dict[tuple[str, str], tuple[str, str]] | None = None


def _load_overrides() -> dict[tuple[str, str], tuple[str, str]]:
    """수동 확정(DART 원문 등) 분류 — 자동 증거로 못 가린 사건을 사람이 정한다."""
    global _overrides
    if _overrides is None:
        _overrides = {}
        if OVERRIDES_CSV.is_file():
            df = pd.read_csv(OVERRIDES_CSV, dtype=str).fillna("")
            for _, r in df.iterrows():
                _overrides[(r["company"], r["term"])] = (r["class"], r["note"])
    return _overrides


RATIO_UP = 1.25
RATIO_DOWN = 0.8
PAID_VS_BONUS_MAX = 0.2  # 유상 현금유입 / 무상 금액 이 이하면 순수 무상으로 본다
CAP_RATIO_TOL = 0.10  # 자본금 증가율과 주식수 증가율 허용 오차


def _amt(v: Any) -> int | None:
    return fm._parse_amount(v)


def _issued_capital(df: pd.DataFrame) -> int | None:
    if df.empty or "account_id" not in df.columns:
        return None
    m = df[(df["sj_div"] == "BS") & (df["account_id"] == "ifrs-full_IssuedCapital")]
    return _amt(m.iloc[0]["thstrm_amount"]) if len(m) else None


def _evidence(df: pd.DataFrame) -> tuple[int, int]:
    """(무상증자 자본금 증가액, 유상증자 현금유입 최대액). 둘 다 해당 분기 누적(YTD) 기준."""
    if df.empty or "account_id" not in df.columns:
        return 0, 0
    nm = df["account_nm"].astype(str)
    aid = df["account_id"].astype(str)
    detail = df["account_detail"].astype(str) if "account_detail" in df.columns else pd.Series("", index=df.index)
    bonus = 0
    for _, r in df[aid.str.contains("BonusIssue") | nm.str.contains("무상증자")].iterrows():
        v = _amt(r["thstrm_amount"])
        if v and v > 0 and ("자본금" in str(r.get("account_detail", "")) or "BonusIssue" in str(r["account_id"])):
            bonus = max(bonus, v)
    paid = 0
    sel = (aid.str.contains("IssueOfEquity|ProceedsFromIssuingShares") | nm.str.contains("유상증자")) & ~nm.str.contains("발행비용|비용")
    for _, r in df[sel].iterrows():
        v = _amt(r["thstrm_amount"])
        if v and v > 0:
            paid = max(paid, v)
    return bonus, paid


def detect_share_events(db: fm.FS_DB, company: str, panel: pd.DataFrame) -> list[dict[str, Any]]:
    """panel: per_share_roll4._panel 결과(term, istc[단위오류 보정 후], FaceValue). 사건 목록(시간순)."""
    events: list[dict[str, Any]] = []
    prev_i = prev_t = prev_fv = None
    prev_k = None
    for k, r in panel.reset_index(drop=True).iterrows():
        i, fv, t = r["istc"], r["FaceValue"], str(r["term"])
        if pd.isna(i) or i <= 0:
            continue
        if prev_i:
            ratio = float(i) / float(prev_i)
            fv_same = pd.notna(fv) and pd.notna(prev_fv) and float(fv) == float(prev_fv)
            if fv_same and (ratio >= RATIO_UP or ratio <= RATIO_DOWN):
                df_t = fm._load_fs_or_empty(db, t, company)
                df_p = fm._load_fs_or_empty(db, prev_t, company)
                bonus, paid = _evidence(df_t)
                c1, c0 = _issued_capital(df_t), _issued_capital(df_p)
                cap_ratio = (c1 / c0) if c0 and c1 else None
                cap_ok = cap_ratio is None or abs(cap_ratio / ratio - 1.0) <= CAP_RATIO_TOL
                if ratio < 1:
                    cls = "감소"
                elif bonus > 0 and cap_ok and paid <= PAID_VS_BONUS_MAX * bonus:
                    cls = "무상증자"
                elif bonus > 0:
                    cls = "무상+유상"
                elif paid > 0:
                    cls = "유상증자"
                else:
                    cls = "불명"
                note = ""
                ov = _load_overrides().get((company, t))
                if ov is not None:
                    cls, note = ov
                events.append(
                    {
                        "company": company,
                        "term": t,
                        "prev_term": prev_t,
                        "idx": int(k),
                        "ratio": round(ratio, 4),
                        "class": cls,
                        "adjusted": cls == "무상증자",
                        "note": note,
                        "bonus_krw": bonus,
                        "paid_krw": paid,
                        "cap_ratio": None if cap_ratio is None else round(cap_ratio, 4),
                    }
                )
        prev_i, prev_t, prev_fv, prev_k = i, t, fv, k
    return events


def apply_bonus_issue_adjustment(panel: pd.DataFrame, events: list[dict[str, Any]]) -> pd.DataFrame:
    """무상증자 사건 이전 분기의 주식수에 증가 배수를 곱해 최신 주식수 기준으로 맞춘다."""
    adj = [e for e in events if e["adjusted"]]
    if not adj:
        return panel
    out = panel.copy().reset_index(drop=True)
    istc = pd.to_numeric(out["istc"], errors="coerce").astype(float)
    for e in adj:
        istc.iloc[: e["idx"]] = istc.iloc[: e["idx"]] * e["ratio"]
    out["istc"] = istc
    return out
