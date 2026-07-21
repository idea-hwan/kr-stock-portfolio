"""
분기 SQLite 재무 DB에서 지표를 계산한다.

**표(sj_nm) 선택·계정(개정) 폴백 정책**은 `docs/fs_resolution.md` 와 모듈 상수
`SJ_NM_FALLBACK` / `SPECS` 를 본다.

루트의 `eps_fps_growth_stock.py` / `earning_growth_stock.py` 와 같은 방식을 쓴다.
  - account_id 우선 (ifrs-full_*, dart_*), 없으면 공백 제거 계정명·부분일치
  - K-IFRS / XBRL 개정에 따라 구 공시는 ifrs_*·신 공시는 ifrs-full_* 가 혼용 →
    `_expand_account_ids` 로 동일 계정의 레거시 id 를 자동 시도 (루트 eps_fps 의 다중 try 와 동일 취지)
  - 연결만 공시하는 경우 손익이 `연결손익계산서` 에만 있을 수 있음 → `_sj_nm_candidates` 로
    손익/현금흐름/재무상태 각각 별도·연결 순 폴백
  - 현금: CFO = ifrs-full_CashFlowsFromUsedInOperatingActivities 등
  - FCF = CFO - 유형취득 - 무형취득 (취득 없으면 0)
  - 분기별 금액: 1분기=당기 누적 그대로, 2~4분기=직전 분기 DB 누적과의 차이
  - TTM FCF: 위 분기 FCF 4개 합 (eps_fps 의 rolling(4) 와 동일 논리)

손익 누적은 반기 보고 등에서 매출 등이 단조가 아닐 수 있어,
사업보고(11011)가 있으면 손익·당기순이익 등 '1년'은 당기 금액을 우선 사용한다.
스냅샷(재무상태표)은 앵커 분기 DB 기말.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.quarter_terms import parse_term
from scripts.stock_db import FS_DB

FINANCIAL_DB_DIR = BASE_DIR / "data" / "financial_statement"
STOCKS_DB_DIR = BASE_DIR / "data" / "stocks"

REPRT_ANNUAL = "11011"

# 어떤 표(sj_nm)를 볼지 — 회사·분기마다 하나만 존재하는 경우가 많아 순서대로 시도한다.
# 정책·예외·운영 절차: docs/fs_resolution.md
SJ_NM_FALLBACK: dict[str, tuple[str, ...]] = {
    "income_statement": (
        "손익계산서",
        "연결손익계산서",
        "포괄손익계산서",
        "연결포괄손익계산서",
    ),
    "cash_flow": ("현금흐름표", "연결현금흐름표"),
    "balance_sheet": ("재무상태표", "연결재무상태표"),
}

# SPECS 의 대표 sj_nm(첫 행) → 위 그룹 키
_SPECS_PRIMARY_SJ_TO_GROUP: dict[str, str] = {
    "손익계산서": "income_statement",
    "현금흐름표": "cash_flow",
    "재무상태표": "balance_sheet",
}

# (sj_nm, account_ids, new_account_nm 정확일치 후보, contains 폴백)
# account_ids: ifrs-full_* 만 적어도 _expand_account_ids 가 ifrs_* 레거시를 같은 순서로 덧붙임.
SPECS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], str | None]] = {
    "revenue": (
        "손익계산서",
        (
            "ifrs-full_Revenue",
            "ifrs-full_RevenueFromContractsWithCustomers",
            "ifrs-full_RevenueFromSaleOfGoods",
        ),
        ("매출액", "수익(매출액)", "영업수익"),
        None,
    ),
    "cogs": ("손익계산서", ("ifrs-full_CostOfSales",), ("매출원가",), None),
    "gross_profit": (
        "손익계산서",
        ("ifrs-full_GrossProfit", "dart_GrossProfit"),
        ("매출총이익",),
        # 공시명에 접두·괄호가 붙은 행 (지주·서비스 등) — exact strip 과 병행
        "매출총이익",
    ),
    "opex": (
        "손익계산서",
        ("dart_TotalSellingGeneralAdministrativeExpenses",),
        ("판매비와관리비",),
        "판매비",
    ),
    "operating_income": (
        "손익계산서",
        (
            "dart_OperatingIncomeLoss",
            "ifrs-full_OperatingIncomeLoss",
            # 영업이익 행 없이 이 라인만 두는 공시 (우리기술투자 등 지주·투자업)
            "ifrs-full_ProfitLossFromOperatingActivities",
            "dart_ProfitLossFromOperatingActivities",
        ),
        (
            "영업이익",
            "영업이익(손실)",
            "계속영업이익",
            "계속영업이익(손실)",
            "영업손익",
            "영업손익(손실)",
            "연결영업이익",
            "연결영업이익(손실)",
            "영업활동으로부터의이익(손실)",
        ),
        # 부분일치는 _pick_from_df 에서 이익률·마진 등 행 제외 후 사용
        "영업이익",
    ),
    "net_income": (
        "손익계산서",
        (
            "ifrs-full_ProfitLoss",
            # 당기순이익 행만 비고 계속영업이익에 금액 있는 공시 (클로봇 사업보고 등)
            "ifrs-full_ProfitLossFromContinuingOperations",
        ),
        (
            "당기순이익",
            "당기순이익(손실)",
            "당기순손익",
            "분기순손익",
            "분기순이익",
            "분기순이익(손실)",
            "반기순이익",
            "반기순이익(손실)",
        ),
        None,
    ),
    # account_id 시도 순서는 _pick_net_income_parent_core (명시 지배 → 당기순−비지배 → 포괄 지배).
    "net_income_parent": (
        "손익계산서",
        (
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "dart_ProfitLossAttributableToOwnersOfParent",
        ),
        (
            "지배기업소유주지분",
            "지배기업의소유주에게귀속되는당기순이익",
            # 구·별도 공시: XBRL 미사용 행에 "지배회사…" 표기 (기아 등). '지배기업' contains 와 불일치.
            "지배회사소유주지분순이익",
            "지배회사소유주지분순이익(손실)",
            "지배회사소유주지분",
            # 포괄손익계산서 단일 표: "지배회사지분순이익" (소유주 생략) — 효성중공업 등
            "지배회사지분순이익",
            "지배회사지분순이익(손실)",
            # 연결포괄: "-표준계정코드 미사용-" + 지배주주순이익 — 고려아연 등
            "지배주주순이익",
            "지배주주순이익(손실)",
            # 청담글로벌 등: "지분" 삽입 표기
            "지배주주지분순이익",
            "지배주주지분순이익(손실)",
            # 삼기에너지솔루션즈 등: "순손익" 표기
            "지배회사지분순손익",
            # 파루 등: 주주·회사 생략 "지배지분…"
            "지배지분순이익",
            "지배지분순손익",
            "지배지분순이익(손실)",
            # 포괄손익: 당기순이익 행 공란·지배 계속영업이익 별도 (클로봇 등)
            "지배기업의소유주계속영업이익(손실)",
            "지배기업의소유주계속영업이익",
        ),
        "지배기업",
    ),
    "finance_cost": ("손익계산서", ("ifrs-full_FinanceCosts",), ("금융비용",), None),
    "eps_basic": ("손익계산서", ("ifrs-full_BasicEarningsLossPerShare",), (), "주당"),
    "eps_diluted": ("손익계산서", ("ifrs-full_DilutedEarningsLossPerShare",), (), None),
    "cfo": (
        "현금흐름표",
        (
            "ifrs-full_CashFlowsFromUsedInOperatingActivities",
            "ifrs-full_CashFlowsFromUsedInOperatingActivitiesContinuingOperations",
        ),
        (),
        "영업활동",
    ),
    "ppe_capex": (
        "현금흐름표",
        ("ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",),
        ("유형자산취득", "유형자산의취득"),
        None,
    ),
    "ia_capex": (
        "현금흐름표",
        ("ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",),
        ("무형자산취득", "무형자산의취득"),
        None,
    ),
    "total_assets": ("재무상태표", ("ifrs-full_Assets",), ("자산총계",), None),
    "total_equity": ("재무상태표", ("ifrs-full_Equity",), ("자본총계",), None),
    "equity_parent": (
        "재무상태표",
        ("ifrs-full_EquityAttributableToOwnersOfParent",),
        ("지배기업소유주지분",),
        "지배기업",
    ),
    "current_assets": ("재무상태표", ("ifrs-full_CurrentAssets",), ("유동자산",), None),
    "current_liabilities": ("재무상태표", ("ifrs-full_CurrentLiabilities",), ("유동부채",), None),
    "cash": ("재무상태표", ("ifrs-full_CashAndCashEquivalents",), ("현금및현금성자산",), None),
    "ar": ("재무상태표", ("ifrs-full_CurrentTradeReceivables",), ("매출채권",), None),
    "inventory": ("재무상태표", ("ifrs-full_Inventories",), ("재고자산",), None),
    "ap": (
        "재무상태표",
        ("ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers",),
        ("매입채무",),
        None,
    ),
    "st_debt": ("재무상태표", (), ("단기차입금",), "단기차입"),
    "lt_debt": (
        "재무상태표",
        ("ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived",),
        ("장기차입금",),
        None,
    ),
    "bonds": ("재무상태표", ("ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued",), ("사채",), None),
    "current_portion_lt": (
        "재무상태표",
        ("ifrs-full_CurrentPortionOfLongtermBorrowings",),
        ("유동성장기부채",),
        None,
    ),
}


def _ifrs_xbrl_variants(account_id: str) -> list[str]:
    """
    DART XBRL: 동일 계정에 ifrs-full_* (신) 과 ifrs_* (구) 가 병행.
    SPECS에는 ifrs-full_* 만 두고, 조회 시 레거시 id 를 자동 추가한다.
    """
    aid = str(account_id).strip()
    if not aid or aid == "-표준계정코드 미사용-":
        return []
    if aid.startswith("ifrs-full_"):
        legacy = "ifrs_" + aid[len("ifrs-full_") :]
        return [aid, legacy]
    if aid.startswith("ifrs_"):
        full = "ifrs-full_" + aid[len("ifrs_") :]
        return [aid, full]
    return [aid]


def _expand_account_ids(ids: tuple[str, ...]) -> list[str]:
    """SPECS 튜플 순서 유지, 변형 id 중복 제거."""
    out: list[str] = []
    for raw in ids:
        for v in _ifrs_xbrl_variants(raw):
            if v not in out:
                out.append(v)
    return out


def _sj_nm_candidates(primary: str) -> tuple[str, ...]:
    """SPECS 의 대표 sj_nm 에 매핑된 표 폴백 순서 (SJ_NM_FALLBACK)."""
    g = _SPECS_PRIMARY_SJ_TO_GROUP.get(primary)
    if g:
        return SJ_NM_FALLBACK[g]
    return (primary,)


def _parse_amount(raw: Any) -> int | None:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = str(raw).strip()
    if s in ("", "-", "nan"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = s.replace(",", "")
    if not re.fullmatch(r"-?\d+", s):
        return None
    v = int(s)
    return -v if neg else v


def _first_nonnull_parsed_amount(amounts: pd.Series) -> int | None:
    """동일 account_id·contains 매칭 행이 여럿일 때 빈 당기금액 행을 건너뜀 (클로봇 등)."""
    for raw in amounts:
        p = _parse_amount(raw)
        if p is not None:
            return p
    return None


# 내재(당기순−비지배): 비지배가 ifrs id 없이 명칭만 있거나, 동일 명칭 행이 둘 이상일 때 정합성으로 짝 맞춤
_NET_INCOME_NCI_STRIPPED_NAMES: tuple[str, ...] = (
    "비지배주주지분순이익",
    "비지배주주지분순이익(손실)",
    "비지배주주순이익",
    "비지배주주순이익(손실)",
    "비지배회사지분순손익",
    "비지배회사지분순이익",
    "비지배회사지분순이익(손실)",
    "비지배지분순이익",
    "비지배지분순손익",
    "비지배지분순이익(손실)",
)


def _parsed_amounts_for_exact_stripped_names(sdf2: pd.DataFrame, names: tuple[str, ...]) -> set[int]:
    out: set[int] = set()
    for nm in names:
        m = sdf2[sdf2["new_account_nm"] == nm]
        for raw in m["thstrm_amount"]:
            p = _parse_amount(raw)
            if p is not None:
                out.add(p)
    return out


def _net_income_parent_implied_total_minus_nci(sdf: pd.DataFrame) -> int | None:
    """
    지배 귀속 당기순(account_id) 행이 없을 때: 연결 당기순이익 − 비지배 귀속 당기순이익.
    반기 등에서 지배 행만 빠지고 비지배·당기순은 있는 공시(성호전자)에 쓰임.
    포괄손익 지배만 두면 OCI 때문에 당기순과 부호가 어긋날 수 있어, 포괄 id 보다 먼저 시도한다.
    """
    if sdf.empty or "account_id" not in sdf.columns or "thstrm_amount" not in sdf.columns:
        return None
    total: int | None = None
    for aid in _expand_account_ids(
        ("ifrs-full_ProfitLoss", "ifrs-full_ProfitLossFromContinuingOperations")
    ):
        m = sdf[sdf["account_id"] == aid]
        if not m.empty:
            p = _first_nonnull_parsed_amount(m["thstrm_amount"])
            if p is not None:
                total = p
                break
    if total is None:
        return None
    nci: int | None = None
    for aid in _expand_account_ids(
        (
            "ifrs-full_ProfitLossAttributableToNoncontrollingInterests",
            "dart_ProfitLossAttributableToNoncontrollingInterests",
        )
    ):
        m = sdf[sdf["account_id"] == aid]
        if not m.empty:
            p = _first_nonnull_parsed_amount(m["thstrm_amount"])
            if p is not None:
                nci = p
                break
    if nci is None:
        # 비지배 행이 ifrs id 없이 명칭만 있거나, 동일 명칭이 중복된 공시(삼기에너지솔루션즈 등):
        # 당기순 − 비지배 후보 = 지배 명칭 행 금액 집합에 들어가는 쌍만 채택
        sdf2 = sdf.copy()
        sdf2["new_account_nm"] = sdf2["account_nm"].astype(str).str.replace(" ", "", regex=False)
        _, _, parent_stripped, _ = SPECS["net_income_parent"]
        parent_vals = _parsed_amounts_for_exact_stripped_names(sdf2, parent_stripped)
        nci_vals = _parsed_amounts_for_exact_stripped_names(sdf2, _NET_INCOME_NCI_STRIPPED_NAMES)
        for n in nci_vals:
            g = total - n
            if g in parent_vals:
                return g
        return None
    return total - nci


def _pick_net_income_parent_core(df: pd.DataFrame) -> int | None:
    """SPECS['net_income_parent'] 기준 sj_nm 폴백 + 명시 id → 내재(당기순−비지배) → 포괄 지배 → 명칭."""
    sj_nm, _owner_tuple, stripped_names, contains = SPECS["net_income_parent"]
    comprehensive_ids = (
        "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent",
        "dart_ComprehensiveIncomeAttributableToOwnersOfParent",
    )
    owner_ids = _expand_account_ids(
        (
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "dart_ProfitLossAttributableToOwnersOfParent",
        )
    )
    for sj in _sj_nm_candidates(sj_nm):
        sdf = df[df["sj_nm"] == sj]
        if sdf.empty:
            continue
        for aid in owner_ids:
            m = sdf[sdf["account_id"] == aid]
            if not m.empty:
                p = _first_nonnull_parsed_amount(m["thstrm_amount"])
                if p is not None:
                    return p
        implied = _net_income_parent_implied_total_minus_nci(sdf)
        if implied is not None:
            return implied
        sdf2 = sdf.copy()
        sdf2["new_account_nm"] = sdf2["account_nm"].astype(str).str.replace(
            " ", "", regex=False
        )
        for nm in stripped_names:
            m = sdf2[sdf2["new_account_nm"] == nm]
            if not m.empty:
                p = _first_nonnull_parsed_amount(m["thstrm_amount"])
                if p is not None:
                    return p
        if contains:
            anm_c = sdf2["new_account_nm"].astype(str)
            mask = anm_c.str.contains(contains.replace(" ", ""), na=False, regex=False)
            mask &= ~anm_c.str.contains(
                r"총포괄|기타포괄|포괄손익",
                na=False,
                regex=True,
            )
            aid_c = sdf2["account_id"].astype(str)
            mask &= ~aid_c.str.contains("ComprehensiveIncome", na=False, regex=False)
            m = sdf2[mask]
            if not m.empty:
                p = _first_nonnull_parsed_amount(m["thstrm_amount"])
                if p is not None:
                    return p
        # 프로이천 등: 지배 당기순 id·명칭 없이 총포괄손익(지배)만 있으면 OCI가 섞인 금액이 됨 → 비지배 실질 분리 없을 때는 연결 당기순이익으로 폴백
        if not _fs_income_indicates_noncontrolling_split(df):
            v_total = _pick_from_df(df, "net_income")
            if v_total is not None:
                return v_total
        for aid in _expand_account_ids(comprehensive_ids):
            m = sdf[sdf["account_id"] == aid]
            if not m.empty:
                p = _first_nonnull_parsed_amount(m["thstrm_amount"])
                if p is not None:
                    return p
    return None


def _fs_income_indicates_noncontrolling_split(df: pd.DataFrame) -> bool:
    """
    손익·포괄손익 표에 **비지배 금액이 실제로 0이 아닌** 행이 있으면 True.
    비지배 행이 이름만 있고 금액이 0(동양생명 등)이면 False → net_income_parent 가 없을 때
    당기순이익 폴백 허용.
    """
    if df.empty or "sj_nm" not in df.columns or "account_nm" not in df.columns:
        return False
    if "thstrm_amount" not in df.columns:
        return False
    sdf = df[df["sj_nm"].isin(SJ_NM_FALLBACK["income_statement"])]
    if sdf.empty:
        return False
    m = sdf["account_nm"].astype(str).str.contains("비지배", na=False)
    if not m.any():
        return False
    for v in sdf.loc[m, "thstrm_amount"]:
        p = _parse_amount(v)
        if p is not None and p != 0:
            return True
    return False


def _pick_from_df(df: pd.DataFrame, key: str) -> int | None:
    if key == "net_income_parent":
        v = _pick_net_income_parent_core(df)
        if v is not None:
            return v
        if not _fs_income_indicates_noncontrolling_split(df):
            return _pick_from_df(df, "net_income")
        return None

    sj_nm, ids, stripped_names, contains = SPECS[key]
    for sj in _sj_nm_candidates(sj_nm):
        sdf = df[df["sj_nm"] == sj]
        if sdf.empty:
            continue
        for aid in _expand_account_ids(ids):
            m = sdf[sdf["account_id"] == aid]
            if not m.empty:
                p = _first_nonnull_parsed_amount(m["thstrm_amount"])
                if p is not None:
                    return p
        sdf2 = sdf.copy()
        sdf2["new_account_nm"] = sdf2["account_nm"].astype(str).str.replace(
            " ", "", regex=False
        )
        for nm in stripped_names:
            m = sdf2[sdf2["new_account_nm"] == nm]
            if not m.empty:
                p = _first_nonnull_parsed_amount(m["thstrm_amount"])
                if p is not None:
                    return p
        if contains:
            # 공백 제거 명과 동일 기준 (DART: "영 업 이 익" 등)
            anm_c = sdf2["new_account_nm"].astype(str)
            mask = anm_c.str.contains(contains.replace(" ", ""), na=False, regex=False)
            if key == "operating_income":
                mask &= ~anm_c.str.contains(
                    r"이익률|이익율|수익률|영업수익률|마진율|손익분기|대비영업이익",
                    na=False,
                    regex=True,
                )
            m = sdf2[mask]
            if not m.empty:
                p = _first_nonnull_parsed_amount(m["thstrm_amount"])
                if p is not None:
                    return p
    # 매출총이익 전용 행이 없고 매출·매출원가만 있는 경우 (SK스퀘어 등 지주/플랫폼)
    if key == "gross_profit":
        rev = _pick_from_df(df, "revenue")
        cogs_v = _pick_from_df(df, "cogs")
        if rev is not None and cogs_v is not None:
            return rev - cogs_v
    return None


def fs_sj_nm_universe(company: str, term: str) -> list[str]:
    """해당 분기 FS 테이블에 실제로 있는 sj_nm 목록 (진단용)."""
    df = _load_fs_or_empty(FS_DB(), term, company)
    if df.empty or "sj_nm" not in df.columns:
        return []
    return sorted(df["sj_nm"].dropna().astype(str).unique().tolist())


def fs_probe_pl_accounts(
    company: str,
    term: str,
    *,
    substr: str = "",
) -> pd.DataFrame:
    """
    손익 관련 sj_nm 행의 account_id·account_nm·당기금액 (개정·연결 대응 점검용).
    `substr` 이 있으면 account_id 또는 account_nm 부분일치 필터.
    """
    df = _load_fs_or_empty(FS_DB(), term, company)
    if df.empty:
        return pd.DataFrame()
    inc_names = SJ_NM_FALLBACK["income_statement"]
    sdf = df[df["sj_nm"].isin(inc_names)].copy()
    if sdf.empty:
        return pd.DataFrame()
    use = sdf[["sj_nm", "account_id", "account_nm", "thstrm_amount"]].drop_duplicates()
    if substr:
        sub = substr.strip()
        m = use["account_id"].astype(str).str.contains(sub, case=False, na=False) | use[
            "account_nm"
        ].astype(str).str.contains(sub, case=False, na=False)
        use = use[m]
    return use.sort_values(["sj_nm", "account_id", "account_nm"]).reset_index(drop=True)


def _terms_chronological(end_term: str, n: int) -> list[str]:
    y, q = parse_term(end_term)
    out: list[str] = []
    for _ in range(n):
        out.append(f"{y}Q{q}")
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    return list(reversed(out))


def _reprt_code(df: pd.DataFrame) -> str | None:
    if df.empty or "reprt_code" not in df.columns:
        return None
    s = df["reprt_code"].dropna().astype(str)
    return s.iloc[0] if len(s) else None


def _load_fs_or_empty(db: FS_DB, term: str, company: str) -> pd.DataFrame:
    path = FINANCIAL_DB_DIR / f"{term}.db"
    if not path.is_file():
        return pd.DataFrame()
    try:
        df = db.read_fs_db(term, company)
        return df if df is not None and not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _load_istc_totqy(term: str, company: str) -> int | None:
    """
    주식총수 DB `istc_totqy`. DART는 행마다 se=보통주/우선주/합계 등이 있어
    iloc[0]이 우선주(금액 '-')인 경우가 있음 → 보통주 행을 우선한다.
    """
    path = STOCKS_DB_DIR / f"{term}.db"
    if not path.is_file():
        return None
    try:
        db = FS_DB()
        df = db.read_stock_db(term, company)
        if df is None or df.empty or "istc_totqy" not in df.columns:
            return None
        if "se" in df.columns:
            common = df[df["se"].astype(str).str.strip() == "보통주"]
            if not common.empty:
                v = _parse_amount(common.iloc[0]["istc_totqy"])
                if v is not None and v > 0:
                    return v
        for _, row in df.iterrows():
            v = _parse_amount(row.get("istc_totqy"))
            if v is not None and v > 0:
                return v
        return _parse_amount(df.iloc[0]["istc_totqy"])
    except Exception:
        return None


def _quarterly_from_cumulative(terms: list[str], cum_values: list[int | None]) -> list[int | None]:
    out: list[int | None] = []
    for i, (term, v) in enumerate(zip(terms, cum_values)):
        if v is None:
            out.append(None)
            continue
        q = int(term.split("Q")[1])
        if q == 1:
            out.append(v)
        else:
            pv = cum_values[i - 1] if i > 0 else None
            out.append(None if pv is None else v - pv)
    return out


def _sum_last_four(values: list[int | None]) -> int | None:
    tail = values[-4:]
    if len(tail) < 4 or any(x is None for x in tail):
        return None
    return sum(tail)  # type: ignore[arg-type]


def compute_metrics(term: str, company: str, roll_quarters: int = 8) -> dict[str, Any]:
    db = FS_DB()
    anchor_df = _load_fs_or_empty(db, term, company)
    if anchor_df.empty:
        raise FileNotFoundError(f"재무 데이터 없음: {company} @ {term}")

    code = _reprt_code(anchor_df)
    notes: list[str] = [
        "계정 추출: account_id(ifrs-full↔ifrs 레거시 자동) → 공백 제거 계정명 → contains. 루트 eps_fps 의 다중 try 와 같은 취지.",
    ]

    chrono = _terms_chronological(term, roll_quarters)
    full_cfo: list[int | None] = []
    full_ppe: list[int | None] = []
    full_ia: list[int | None] = []

    for t in chrono:
        df = _load_fs_or_empty(db, t, company)
        if df.empty:
            full_cfo.append(None)
            full_ppe.append(None)
            full_ia.append(None)
            continue
        c = _pick_from_df(df, "cfo")
        ppe = _pick_from_df(df, "ppe_capex")
        ia = _pick_from_df(df, "ia_capex")
        full_cfo.append(c)
        full_ppe.append(ppe if ppe is not None else 0)
        full_ia.append(ia if ia is not None else 0)

    fcf_cum: list[int | None] = []
    for c, p, i in zip(full_cfo, full_ppe, full_ia):
        if c is None:
            fcf_cum.append(None)
        else:
            fcf_cum.append(c - (p or 0) - (i or 0))

    q_fcf = _quarterly_from_cumulative(chrono, fcf_cum)
    ttm_fcf = _sum_last_four(q_fcf)

    pl_1y: dict[str, int | None] = {}
    use_fy = code == REPRT_ANNUAL
    if use_fy:
        for k in (
            "revenue",
            "cogs",
            "gross_profit",
            "opex",
            "operating_income",
            "net_income",
            "net_income_parent",
            "finance_cost",
            "eps_basic",
            "eps_diluted",
        ):
            pl_1y[k] = _pick_from_df(anchor_df, k)
        notes.append("손익 1년: 사업보고(11011) 당기(thstrm) 사용.")
    else:
        pl_1y = {
            k: None
            for k in (
                "revenue",
                "cogs",
                "gross_profit",
                "opex",
                "operating_income",
                "net_income",
                "net_income_parent",
                "finance_cost",
                "eps_basic",
                "eps_diluted",
            )
        }
        notes.append(
            f"앵커가 사업보고가 아님(reprt_code={code}). "
            "손익 1년은 미채움 — 분기 누적 차분·TTM 손익은 별도 검증 후 확장."
        )

    bs: dict[str, int | None] = {k: _pick_from_df(anchor_df, k) for k in (
        "total_assets", "total_equity", "equity_parent", "current_assets",
        "current_liabilities", "cash", "ar", "inventory", "ap",
        "st_debt", "lt_debt", "bonds", "current_portion_lt",
    )}
    st_d = bs["st_debt"] or 0
    lt_d = bs["lt_debt"] or 0
    bonds = bs["bonds"] or 0
    cplt = bs["current_portion_lt"] or 0
    gross_debt = st_d + lt_d + bonds + cplt

    ocf_1y = _pick_from_df(anchor_df, "cfo") if use_fy else None
    ppe_1y = _pick_from_df(anchor_df, "ppe_capex") if use_fy else None
    ia_1y = _pick_from_df(anchor_df, "ia_capex") if use_fy else None
    capex_1y = None
    if ppe_1y is not None or ia_1y is not None:
        capex_1y = (ppe_1y or 0) + (ia_1y or 0)
    fcf_fy = None
    if ocf_1y is not None and capex_1y is not None:
        fcf_fy = ocf_1y - capex_1y

    if ttm_fcf is not None and fcf_fy is not None and fcf_fy != 0:
        if abs(ttm_fcf - fcf_fy) / abs(fcf_fy) > 0.02:
            notes.append(
                f"TTM FCF(분기차분 4Q 합)={ttm_fcf:,} vs 사업보고 FCF={fcf_fy:,} — 2% 초과 차이."
            )

    revenue = pl_1y.get("revenue")
    gross_profit = pl_1y.get("gross_profit")
    op_inc = pl_1y.get("operating_income")
    net_inc = pl_1y.get("net_income")
    net_parent = pl_1y.get("net_income_parent")
    fin_cost = pl_1y.get("finance_cost")

    def div(a: int | None, b: int | None) -> float | None:
        if a is None or b is None or b == 0:
            return None
        return a / b

    ratios: dict[str, float | None] = {
        "gross_margin": div(gross_profit, revenue),
        "operating_margin": div(op_inc, revenue),
        "net_margin": div(net_inc, revenue),
        "roe_parent": div(net_parent, bs["equity_parent"]),
        "roe_consolidated": div(net_inc, bs["total_equity"]),
        "roa": div(net_inc, bs["total_assets"]),
        "current_ratio": div(bs["current_assets"], bs["current_liabilities"]),
        "cash_conversion_ratio": div(ocf_1y, net_inc),
        "fcf_margin_ttm_roll4": div(ttm_fcf, revenue),
        "fcf_margin_fy_filing": div(fcf_fy, revenue),
        "net_debt_to_equity_parent": div(
            gross_debt - bs["cash"] if bs["cash"] is not None else None,
            bs["equity_parent"],
        ),
        "interest_coverage_op_over_finance_cost": div(op_inc, fin_cost),
    }

    istc = _load_istc_totqy(term, company)
    derived: dict[str, Any] = {}
    if istc and net_parent is not None:
        derived["ni_parent_over_istc_totqy_row0_won"] = net_parent / istc

    return {
        "meta": {
            "company": company,
            "term": term,
            "reprt_code": code,
            "is_annual_report": use_fy,
            "reference_scripts": [
                "eps_fps_growth_stock.py",
                "earning_growth_stock.py",
            ],
            "flow_1y_pnl": "사업보고 당기(thstrm) 우선",
            "flow_ttm_fcf": "CFO−PPE−IA 누적 → 분기 차분 → 최근 4분기 합",
            "snapshot": "앵커 분기 재무상태표 기말",
        },
        "income_statement_1y_krw": pl_1y,
        "cash_flow_fy_krw": {
            "operating_cash_flow": ocf_1y,
            "capex_ppe": ppe_1y,
            "capex_intangible": ia_1y,
            "fcf_ocf_minus_capex": fcf_fy,
        },
        "fcf_roll4_detail": {
            "terms": chrono,
            "quarterly_fcf_est": q_fcf,
            "ttm_fcf_sum_last_4q": ttm_fcf,
        },
        "balance_sheet_snapshot_krw": {
            **bs,
            "gross_debt": gross_debt,
            "net_debt": gross_debt - bs["cash"] if bs["cash"] is not None else None,
        },
        "ratios": ratios,
        "shares": {"istc_totqy_row0": istc},
        "derived": derived,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="재무 DB 지표 (루트 eps_fps 스타일 추출 + TTM FCF 롤4)"
    )
    p.add_argument("--company", default="삼성전자")
    p.add_argument("--term", default="2025Q4")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--probe-pl",
        action="store_true",
        help="손익계산서·연결손익계산서 계정 목록 출력 (매핑·개정 점검)",
    )
    p.add_argument(
        "--probe-filter",
        default="",
        help="--probe-pl 시 account_id/nm 부분일치 필터 (예: Revenue, 매출)",
    )
    p.add_argument(
        "--probe-sj",
        action="store_true",
        help="해당 분기 FS 에 존재하는 sj_nm 전체 목록만 출력",
    )
    args = p.parse_args(argv)

    if args.probe_sj:
        names = fs_sj_nm_universe(args.company, args.term)
        if not names:
            print(f"no FS rows: {args.company} @ {args.term}", file=sys.stderr)
            return 1
        print(f"company={args.company} term={args.term}")
        for n in names:
            print(f"  {n}")
        return 0

    if args.probe_pl:
        tdf = fs_probe_pl_accounts(
            args.company, args.term, substr=args.probe_filter or ""
        )
        if tdf.empty:
            print(
                f"no 손익/연결손익 rows (or no match): {args.company} @ {args.term}",
                file=sys.stderr,
            )
            return 1
        with pd.option_context("display.max_rows", 300, "display.width", 160):
            print(tdf.to_string(index=False))
        return 0

    try:
        result = compute_metrics(args.term, args.company)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    meta = result["meta"]
    print(f"회사: {meta['company']}  앵커: {meta['term']}  reprt_code: {meta['reprt_code']}")
    print(f"참고 스크립트: {', '.join(meta['reference_scripts'])}")
    if not meta["is_annual_report"]:
        print("⚠ 사업보고 아님 — 손익 1년 필드는 비었을 수 있음.")
    print()

    print("=== 손익 1년 (원, 사업보고 당기) ===")
    for k, v in result["income_statement_1y_krw"].items():
        print(f"  {k}: {v:,}" if isinstance(v, int) else f"  {k}: {v}")
    print()

    print("=== 현금흐름 (사업보고 당기, 원) ===")
    for k, v in result["cash_flow_fy_krw"].items():
        print(f"  {k}: {v:,}" if isinstance(v, int) else f"  {k}: {v}")
    roll = result["fcf_roll4_detail"]
    print()
    print("=== TTM FCF (분기 CFO−PPE−IA 차분 × 4Q) ===")
    print(f"  ttm_fcf: {roll['ttm_fcf_sum_last_4q']:,}" if roll["ttm_fcf_sum_last_4q"] else "  ttm_fcf: —")
    print(f"  분기값: {roll['quarterly_fcf_est'][-4:]}")
    print()

    print("=== 재무상태표 기말 (원) ===")
    bs = result["balance_sheet_snapshot_krw"]
    for k, v in bs.items():
        if isinstance(v, int):
            print(f"  {k}: {v:,}")
        else:
            print(f"  {k}: {v}")
    print()

    print("=== 비율 ===")
    for k, v in result["ratios"].items():
        print(f"  {k}: {v:.4f}" if v is not None else f"  {k}: —")

    if result["derived"]:
        print()
        print("=== 파생 (istc_totqy 행0, eps_fps 와 동일) ===")
        for k, v in result["derived"].items():
            print(f"  {k}: {v:,.2f}")
        print(f"  istc_totqy: {result['shares']['istc_totqy_row0']:,}")

    if result["notes"]:
        print()
        print("=== 참고 ===")
        for n in result["notes"]:
            print(f"  - {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
