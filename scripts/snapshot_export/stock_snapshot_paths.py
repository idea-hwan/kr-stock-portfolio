"""버킷별 공통 스냅샷 CSV 기본 경로·DB 경로."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_TTM_VALUATION_DB = _ROOT / "data" / "analytics" / "ttm_valuation.db"
DEFAULT_GROWTH_DB = _ROOT / "data" / "analytics" / "ttm_metric_growth.db"

DEFAULT_CYCLICAL_MANUAL_TXT = _ROOT / "stock_data" / "cyclical_manual_universe.txt"

# 공통 포맷 스냅샷 (stock_snapshot_core.build_stock_snapshot_df 산출과 동일 컬럼)
# PIT 교정 전 "오늘 통과 종목만" 스냅샷 — 생존편향 있음, mcap200_factor_panel.csv +
# pit_buckets.db 조합으로 대체됨. 재현 가능한 산출물이라 scratch/ 에 둔다.
DEFAULT_BUCKET_CSV: dict[str, Path] = {
    "cyclical": _ROOT / "data" / "analytics" / "scratch" / "cyclical_stock.csv",
    "large_value": _ROOT / "data" / "analytics" / "scratch" / "large_value_stock.csv",
    "large_growth": _ROOT / "data" / "analytics" / "scratch" / "large_growth_stock.csv",
}

BUCKET_KEYS: tuple[str, ...] = tuple(DEFAULT_BUCKET_CSV.keys())
