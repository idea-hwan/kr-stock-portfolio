"""
잠정실적(연결재무제표기준영업(잠정)실적, 공정공시)의 영업이익을 TTM 주당 영업이익에
앞당겨 반영 — 정식 분기·반기·사업보고서가 나오기 전 P/OP(20d/4y) 얼리 시그널.

data/analytics/preliminary_earnings.db (scripts/pipeline/collect_preliminary_earnings.py)
가 채운 (company, term) 당 매출액·영업이익만 있고 주식수·액면가는 없다 — 직전 확정
분기의 주식수·액면가를 그대로 이월(carry-forward)해서 근사한다(대형주는 단기간 변동이
작아 합리적 근사, 정확한 방식이 아니라 근사임을 배지로 명시할 것).

기존 검증된 함수만 재사용한다 — 새 TTM/PER 계산 로직을 여기서 새로 만들지 않는다:
  - scripts/analysis/per_share_roll4.py 의 _panel/_add_quarterly_cum/_ttm_per_share_eps_fps
    (분기 diff·TTM 롤4 주당 계산, eps_fps 레일과 동일)
  - scripts/analysis/series_per.py 의 enrich_ttm_series_with_per (가격·PER·P/OP 20d/4y,
    공시 앵커일이 미래면 오늘로 clip하는 기존 로직을 그대로 재사용)

data/analytics/ttm_valuation.db, data/analytics/mcap200_factor_panel.csv 는 이 모듈이
절대 쓰지 않는다 — 백테스트·확정 신호가 쓰는 원본이라 오염시키지 않고, 대시보드가 매번
호출하는 인메모리 오버레이로만 쓴다(build_dashboard.py 에서 호출).

  .venv/bin/python scripts/analysis/provisional_ttm.py --company 삼성전자 --term 2026Q1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis import fs_metrics as fm  # noqa: E402
from scripts.analysis import per_share_roll4 as roll4  # noqa: E402
from scripts.analysis.series_per import enrich_ttm_series_with_per  # noqa: E402
from scripts.quarter_terms import shift_term  # noqa: E402

PRELIMINARY_DB = _ROOT / "data" / "analytics" / "preliminary_earnings.db"


def build_provisional_op_row(
    company: str, official_anchor_term: str, provisional_term: str, provisional_op_krw: int
) -> dict | None:
    """직전 3개 확정 분기(올바르게 diff된 q_operating_income) + 잠정치 1개 분기로
    TTM 주당 영업이익을 근사. 확정 분기 중 하나라도 결측이면 None(위에 덧대지 않음)."""
    db = fm.FS_DB()
    lead_in = shift_term(official_anchor_term, -3)
    chrono = roll4._chrono_terms(lead_in, official_anchor_term)  # 4개 텀(리드인 1개 포함, diff 정확성용)
    panel = roll4._panel(db, company, chrono)
    roll4._add_quarterly_cum(panel, "operating_income", "q_operating_income")
    last3 = panel.tail(3)
    if last3["q_operating_income"].isna().any():
        return None

    last_row = last3.iloc[-1]
    synthetic = pd.DataFrame(
        [
            {
                "term": provisional_term,
                "FaceValue": last_row["FaceValue"],
                "istc_ffill": last_row["istc_ffill"],
                "q_operating_income": provisional_op_krw,
            }
        ]
    )
    four = pd.concat(
        [last3[["term", "FaceValue", "istc_ffill", "q_operating_income"]], synthetic],
        ignore_index=True,
    )
    op_ps = roll4._ttm_per_share_eps_fps(four, "q_operating_income")
    if op_ps is None:
        return None
    return {
        "op_ps_provisional": op_ps,
        "carried_from_term": official_anchor_term,
        "istc_ffill_carried": float(last_row["istc_ffill"]) if pd.notna(last_row["istc_ffill"]) else None,
        "face_value_carried": float(last_row["FaceValue"]) if pd.notna(last_row["FaceValue"]) else None,
    }


def build_provisional_per_op(
    company: str,
    official_anchor_term: str,
    provisional_term: str,
    provisional_op_krw: int,
    n_quarters: int = 20,
) -> dict | None:
    """확정 시계열(compute_ttm_series, 미변경) + 잠정 1개 행을 이어붙여
    enrich_ttm_series_with_per()를 그대로 호출 — 오늘 날짜로 clip되는 기존 로직을
    재사용해 as-of-today P/OP(20d/4y)를 얻는다."""
    built = build_provisional_op_row(company, official_anchor_term, provisional_term, provisional_op_krw)
    if built is None:
        return None

    r = roll4.compute_ttm_series(official_anchor_term, company, n_quarters=n_quarters)
    r["series"].append(
        {
            "ttm_end_term": provisional_term,
            "roll4_pl_per_share_eps_fps": {"operating_income": built["op_ps_provisional"]},
            "income_per_share_won_fy_if_q4_annual": {},
            "face_value_at_end": None,  # ffill/bfill로 직전 확정 분기 값이 자동 이월됨
        }
    )
    enrich_ttm_series_with_per(r, company)
    prow = r["series"][-1]

    per_op_20d = prow.get("per_op_20d_mean")
    per_op_4y = prow.get("per_op_4y_mean")
    if per_op_20d is None and per_op_4y is None:
        return None

    return {
        "per_op_20d": per_op_20d,
        "per_op_4y": per_op_4y,
        "op_ps_provisional": built["op_ps_provisional"],
        "carried_from_term": built["carried_from_term"],
    }


def preliminary_row(company: str, term: str) -> dict | None:
    """data/analytics/preliminary_earnings.db 에서 (company, term) 행 조회."""
    import sqlite3

    if not PRELIMINARY_DB.is_file():
        return None
    con = sqlite3.connect(PRELIMINARY_DB)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM preliminary_earnings WHERE company = ? AND term = ?", (company, term)
    ).fetchone()
    con.close()
    return dict(row) if row else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--company", required=True)
    p.add_argument("--term", required=True, help="확정 최신 앵커 분기 (예: 2026Q1)")
    args = p.parse_args()

    provisional_term = shift_term(args.term, 1)
    prelim = preliminary_row(args.company, provisional_term)
    if prelim is None:
        print(f"{args.company}: {provisional_term} 잠정실적 없음 (먼저 collect_preliminary_earnings.py 실행)")
        return 1
    if prelim.get("operating_income_krw") is None:
        print(f"{args.company}: {provisional_term} 잠정실적에 영업이익 없음")
        return 1

    result = build_provisional_per_op(
        args.company, args.term, provisional_term, prelim["operating_income_krw"]
    )
    if result is None:
        print(f"{args.company}: 확정 분기 데이터 부족 또는 가격 조회 실패 — 잠정치 계산 불가")
        return 1

    print(f"{args.company} — 확정 앵커 {args.term} → 잠정 {provisional_term}")
    print(f"  잠정 영업이익(당해): {prelim['operating_income_krw']:,} 원 (공시일 {prelim['rcept_dt']})")
    print(f"  TTM 주당 영업이익(잠정): {result['op_ps_provisional']:,.2f}")
    print(f"  P/OP(20d, 잠정): {result['per_op_20d']}")
    print(f"  P/OP(4y, 잠정):  {result['per_op_4y']}")
    print(f"  (주식수·액면가는 {result['carried_from_term']} 확정 분기 값 이월)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
