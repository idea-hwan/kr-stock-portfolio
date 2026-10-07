"""
상위 200종목의 주식수 변동 사건(액면가 불변)을 감지해 data/analytics/share_events.csv 로 저장.
대시보드가 읽어 종목별 주석(무상증자 보정 적용 / 무상+유상 혼재 미보정 등)을 보여준다.
분류·보정 규칙은 scripts/analysis/share_events.py 참고.

  .venv/bin/python scripts/analysis/build_share_events.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis import fs_metrics as fm
from scripts.analysis import per_share_roll4 as p

MCAP_CSV = _ROOT / "stock_data" / "mcap_top_200.csv"
OUT_CSV = _ROOT / "data" / "analytics" / "share_events.csv"


def main() -> int:
    names = pd.read_csv(MCAP_CSV)["Name"].tolist()
    db = fm.FS_DB()
    latest = max(t for t in p._list_fs_db_terms())
    chrono = p._chrono_terms("2016Q4", latest)
    rows = []
    for i, c in enumerate(names, 1):
        try:
            panel = p._panel(db, c, chrono)
        except Exception as e:  # 액면가 미확정 등
            print(f"[{i}/{len(names)}] {c} 건너뜀: {str(e)[:60]}", file=sys.stderr)
            continue
        rows.extend(panel.attrs.get("share_events", []))
    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}  events={len(out)}")
    print(out["class"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
