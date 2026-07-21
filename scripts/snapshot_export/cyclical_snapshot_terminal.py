"""
경기순환 유니버스 종목 **단일 종목** 스냅샷을 터미널(또는 소량 CSV)로 본다. 선정·시뮬 없음.

데이터 행은 **`stock_snapshot_core.build_stock_snapshot_df`** 와 동일. 전 유니버스 CSV는
**`export_bucket_stock_csv.py --bucket cyclical`** 로보낸다.

- 표 컬럼: 앵커일·종가 → 주당·PER → 기하 성장률 → 선행 수익률(`ret_*`).
- 기본 **전 분기** 출력. `--min-quarters N` 으로 앞쪽 N분기 생략.
- 수익률: per_anchor_trade_date 종가 매수 → N개월 후 이전 영업일 종가 매도.

예:
  .venv/bin/python scripts/snapshot_export/cyclical_snapshot_terminal.py
  .venv/bin/python scripts/snapshot_export/cyclical_snapshot_terminal.py --company SK하이닉스
  .venv/bin/python scripts/snapshot_export/cyclical_snapshot_terminal.py --company 삼성전자 --wide
  .venv/bin/python scripts/snapshot_export/cyclical_snapshot_terminal.py --company 삼성전자 --csv /tmp/sam.csv
  .venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket cyclical
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis.ttm_valuation_df import DEFAULT_DB
from scripts.snapshot_export.stock_snapshot_core import (
    GROWTH_GEOM_KEYS,
    GROWTH_GEOM_KEYS_CF,
    GROWTH_GEOM_KEYS_PL,
    build_stock_snapshot_df,
)

# 터미널 표 헤더 (DB 컬럼명과 구분)
_COLUMN_LABELS: dict[str, str] = {
    "ttm_end_term": "분기",
    "per_anchor_trade_date": "앵커일",
    "per_anchor_close": "종가(원)",
    "face_value_end": "액면",
    "op_ps": "영업/주",
    "ni_parent_ps": "지배순/주",
    "capex_ps": "capex/주",
    "cfo_ps": "cfo/주",
    "fcf_ps": "fcf/주",
    "per_ni_4y": "P/E·4y",
    "per_ni_20d": "P/E·20d",
    "per_op_4y": "P/영업·4y",
    "per_op_20d": "P/영업·20d",
    "per_rev_4y": "P/매출·4y",
    "per_rev_20d": "P/매출·20d",
    "rev_geom_1y_mcum": "매출·1y%",
    "rev_geom_2y_mcum": "매출·2y%",
    "rev_geom_4y_mcum": "매출·4y%",
    "op_geom_1y_mcum": "영업·1y%",
    "op_geom_2y_mcum": "영업·2y%",
    "op_geom_4y_mcum": "영업·4y%",
    "ni_geom_1y_mcum": "순이익·1y%",
    "ni_geom_2y_mcum": "순이익·2y%",
    "ni_geom_4y_mcum": "순이익·4y%",
    "capex_geom_1y_mcum": "capex·1y%",
    "capex_geom_2y_mcum": "capex·2y%",
    "capex_geom_4y_mcum": "capex·4y%",
    "cfo_geom_1y_mcum": "cfo·1y%",
    "cfo_geom_2y_mcum": "cfo·2y%",
    "cfo_geom_4y_mcum": "cfo·4y%",
    "fcf_geom_1y_mcum": "fcf·1y%",
    "fcf_geom_2y_mcum": "fcf·2y%",
    "fcf_geom_4y_mcum": "fcf·4y%",
}


def run_terminal_snapshot(
    company: str,
    *,
    db_path: Path,
    growth_db: Path | None,
    min_quarters: int,
    forward_months: list[int],
    anchor_term: str | None,
    computed_at: str | None,
) -> tuple[pd.DataFrame, str | None]:
    """`build_stock_snapshot_df` 별칭 (하위 호환·스크립트 내부용)."""
    return build_stock_snapshot_df(
        company,
        db_path=db_path,
        growth_db=growth_db,
        min_quarters=min_quarters,
        forward_months=forward_months,
        anchor_term=anchor_term,
        computed_at=computed_at,
    )


def _ret_col_label(col: str) -> str:
    if col.startswith("ret_") and col.endswith("m"):
        try:
            m = int(col[4:-1])
            return f"{m}m 수익률"
        except ValueError:
            pass
    return col


def _is_na_val(v: object) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _fmt_display_cell(col: str, v: object) -> str:
    if _is_na_val(v):
        return "—"
    if col.startswith("ret_"):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return str(v)
        return f"{100.0 * x:+.2f}%"
    if col == "per_anchor_close":
        try:
            return f"{float(v):,.0f}"
        except (TypeError, ValueError):
            return str(v)
    if col in ("face_value_end", "op_ps", "ni_parent_ps", "capex_ps", "cfo_ps", "fcf_ps"):
        try:
            return f"{float(v):,.2f}"
        except (TypeError, ValueError):
            return str(v)
    if col in GROWTH_GEOM_KEYS:
        try:
            return f"{float(v):+.2f}%"
        except (TypeError, ValueError):
            return str(v)
    if col.startswith("per_"):
        try:
            return f"{float(v):.2f}"
        except (TypeError, ValueError):
            return str(v)
    return str(v)


def build_terminal_display_table(out: pd.DataFrame) -> pd.DataFrame:
    disp = out.copy()
    for c in disp.columns:
        disp[c] = [_fmt_display_cell(c, v) for v in out[c].values]
    return disp


def print_terminal_readable(out: pd.DataFrame, company: str) -> None:
    ts = shutil.get_terminal_size(fallback=(160, 40))
    term_w = max(100, min(ts.columns, 280))
    disp = build_terminal_display_table(out)
    ret_cols = [c for c in disp.columns if c.startswith("ret_")]

    groups: list[tuple[str, str | None, list[str]]] = [
        (
            "[1] 앵커 · 가격 · 주당 · 배수",
            "앵커일·종가·액면·주당 지표 → P/E·P/영업·P/매출 (각 4y·20d 평균).",
            [
                "per_anchor_trade_date",
                "per_anchor_close",
                "face_value_end",
                "op_ps",
                "ni_parent_ps",
                "capex_ps",
                "cfo_ps",
                "fcf_ps",
                "per_ni_4y",
                "per_ni_20d",
                "per_op_4y",
                "per_op_20d",
                "per_rev_4y",
                "per_rev_20d",
            ],
        ),
        (
            "[2a] 기하 누적 성장률 — 손익 (매출·영업·순이익, 각 1y·2y·4y)",
            "단위: % (ttm_metric_growth_series).",
            list(GROWTH_GEOM_KEYS_PL),
        ),
        (
            "[2b] 기하 누적 성장률 — 현금흐름 (capex·cfo·fcf, 각 1y·2y·4y)",
            "단위: % (동일 DB).",
            list(GROWTH_GEOM_KEYS_CF),
        ),
        (
            "[3] 선행 수익률 (앵커일 종가 매수 → N개월 후 매도)",
            None,
            ret_cols,
        ),
    ]

    bar_w = min(term_w - 4, 72)
    bar = "═" * bar_w
    thin = "─" * bar_w
    print(f"\n{bar}\n  {company}\n{thin}")

    idx = (
        out["ttm_end_term"].astype(str).values
        if "ttm_end_term" in out.columns
        else None
    )

    with pd.option_context(
        "display.unicode.east_asian_width",
        True,
        "display.max_rows",
        200,
        "display.width",
        term_w,
        "display.max_colwidth",
        22,
        "display.precision",
        2,
    ):
        for title, subtitle, want_cols in groups:
            cols = [c for c in want_cols if c in disp.columns]
            if not cols:
                continue
            sub = disp[cols].copy()
            rename = {
                c: _COLUMN_LABELS.get(c, _ret_col_label(c) if c.startswith("ret_") else c)
                for c in sub.columns
            }
            sub = sub.rename(columns=rename)
            if idx is not None and len(sub) == len(idx):
                sub.insert(0, "분기", idx)
            print(f"\n{title}")
            if subtitle:
                print(f"    {subtitle}")
            print(
                sub.to_string(
                    index=False,
                    col_space=3,
                )
            )

    print(f"\n{thin}\n  행 {len(out)}개 · 넓은 원시표: --wide\n")


def print_terminal_wide_raw(out: pd.DataFrame, company: str) -> None:
    term_w = max(120, shutil.get_terminal_size(fallback=(160, 24)).columns)
    print(f"\n=== {company} ===\n")
    with pd.option_context(
        "display.unicode.east_asian_width",
        True,
        "display.max_rows",
        200,
        "display.width",
        term_w,
    ):
        print(out.to_string(index=False))


def main() -> int:
    p = argparse.ArgumentParser(
        description="경기순환용 단일 종목 스냅샷 터미널 표 (CSV는 export_bucket_stock_csv 사용)"
    )
    p.add_argument(
        "--company",
        default="삼성전자",
        help="종목명 (stock_listing Name, 기본 삼성전자)",
    )
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="ttm_valuation.db")
    p.add_argument(
        "--growth-db",
        type=Path,
        default=None,
        help="ttm_metric_growth.db (기본 data/analytics/ttm_metric_growth.db)",
    )
    p.add_argument(
        "--min-quarters",
        type=int,
        default=0,
        metavar="N",
        help="앞에서 N분기 건너뛰기. 기본 0=전체",
    )
    p.add_argument(
        "--forward-months",
        type=int,
        nargs="+",
        default=[12, 15, 18],
        help="선행 수익률 개월 (기본 12·15·18)",
    )
    p.add_argument("--anchor-term", default=None, help="특정 anchor_term 필터")
    p.add_argument("--computed-at", default=None, help="특정 배치")
    p.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="단일 종목 결과를 CSV로 저장 (선택)",
    )
    p.add_argument(
        "--wide",
        action="store_true",
        help="섹션 대신 원시 숫자 한 표",
    )
    args = p.parse_args()

    company = args.company
    out, err = run_terminal_snapshot(
        company,
        db_path=args.db,
        growth_db=args.growth_db,
        min_quarters=args.min_quarters,
        forward_months=args.forward_months,
        anchor_term=args.anchor_term,
        computed_at=args.computed_at,
    )
    if err:
        print(f"{company}: {err}", file=sys.stderr)
        return 1
    if out.empty:
        print(f"{company}: 빈 결과", file=sys.stderr)
        return 1

    if args.wide:
        print_terminal_wide_raw(out, company)
    else:
        print_terminal_readable(out, company)

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(args.csv, index=False)
        print(f"\nWrote {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
