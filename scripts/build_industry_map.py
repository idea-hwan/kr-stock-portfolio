"""
mcap200 종목별 업종명 캐시 생성 — DART induty_code(업종 코드) → 표준산업분류명 매핑.

DART company() API는 업종 "코드"(숫자)만 주고 실제 업종명 텍스트는 안 준다. 코드표는
FinanceData/KSIC 저장소(제10차 한국표준산업분류, 2017~)의 CSV를 그대로 받아
stock_data/ksic_industry_codes.csv 로 저장해뒀다. 이 스크립트가 그 둘을 이어붙여
data/analytics/industry_map.csv 를 만든다 — 업종 분류는 거의 안 바뀌므로(회사가 사업목적을
변경하지 않는 한) 대시보드 빌드마다 다시 조회하지 않고 이 캐시를 읽는다.

  .venv/bin/python scripts/build_industry_map.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

MCAP_CSV = _ROOT / "stock_data" / "mcap_top_200.csv"
KSIC_CSV = _ROOT / "stock_data" / "ksic_industry_codes.csv"
OUT_CSV = _ROOT / "data" / "analytics" / "industry_map.csv"


def _load_dart_key() -> str:
    env_path = _ROOT / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("DART_API_KEY"):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(".env 에 DART_API_KEY 없음")


def main() -> int:
    import OpenDartReader

    dart = OpenDartReader(_load_dart_key())
    ksic = pd.read_csv(KSIC_CSV, dtype=str)
    ksic_map = dict(zip(ksic["Industy_code"], ksic["Industy_name"]))

    def _lookup(code: str | None) -> str:
        if not code:
            return "—"
        code = str(code).strip()
        for n in (len(code), 5, 4, 3, 2):
            prefix = code[:n]
            if prefix in ksic_map:
                return ksic_map[prefix]
        return "—"

    mcap = pd.read_csv(MCAP_CSV, dtype={"Code": str})
    rows = []
    for i, row in mcap.iterrows():
        code, name = row["Code"], row["Name"]
        try:
            info = dart.company(code)
            induty_code = info.get("induty_code")
            industry = _lookup(induty_code)
        except Exception as e:
            induty_code, industry = None, "—"
            print(f"[{i + 1}/{len(mcap)}] {name} ERROR: {e}", file=sys.stderr)
        rows.append({"company": name, "code": code, "induty_code": induty_code, "industry": industry})
        if (i + 1) % 50 == 0:
            print(f"... {i + 1}/{len(mcap)}", file=sys.stderr)
        time.sleep(0.05)

    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    n_missing = (out["industry"] == "—").sum()
    print(f"Wrote {OUT_CSV}  rows={len(out)}  missing={n_missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
