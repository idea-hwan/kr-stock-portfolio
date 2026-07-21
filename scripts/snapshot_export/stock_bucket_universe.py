"""버킷별 종목명 리스트 (stock_classification.db 미사용)."""

from __future__ import annotations

from pathlib import Path

from scripts.manual_lists import load_cyclical_manual_universe
from scripts.snapshot_export.stock_snapshot_paths import DEFAULT_CYCLICAL_MANUAL_TXT


def cyclical_manual_universe(manual_path: Path = DEFAULT_CYCLICAL_MANUAL_TXT) -> list[str]:
    """`cyclical_manual_universe.txt` — 편입 순서 유지, `- 이름` 제외."""
    return load_cyclical_manual_universe(manual_path)
