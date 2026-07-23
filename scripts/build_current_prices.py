"""
mcap200 종목별 현재가 + 1w/1m/3m/1y trailing(후행) 수익률 캐시.

대시보드 메인 테이블의 "지금 얼마인지·최근에 얼마나 움직였는지"용 — 확정 신호(forward
수익률)와는 별개 지표라 별도 캐시로 분리했다. 라이브 가격 조회(FinanceDataReader, 종목당
1회)라 시간이 좀 걸리고, 주가는 매일 바뀌므로 build_dashboard.py가 매번 다시 부르지 않고
이 스크립트를 필요할 때(하루 한 번 정도) 따로 돌려서 캐시를 갱신하는 구조다 — us-stock-
portfolio의 data/analytics/valuation_current.json과 같은 역할.

  .venv/bin/python scripts/build_current_prices.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

MCAP_CSV = _ROOT / "stock_data" / "mcap_top_200.csv"
OUT_CSV = _ROOT / "data" / "analytics" / "current_prices.csv"

HORIZONS = {"1w": pd.DateOffset(weeks=1), "1m": pd.DateOffset(months=1), "3m": pd.DateOffset(months=3), "1y": pd.DateOffset(years=1)}


def _asof(px: pd.DataFrame, d: pd.Timestamp) -> float | None:
    sub = px.loc[px["Date"] <= d]
    if sub.empty:
        return None
    return float(sub["Close"].iloc[-1])


def main() -> int:
    import FinanceDataReader as fdr

    mcap = pd.read_csv(MCAP_CSV, dtype={"Code": str})
    rows = []
    n = len(mcap)
    for i, row in mcap.iterrows():
        code, name = row["Code"], row["Name"]
        print(f"[{i + 1}/{n}] {name}", file=sys.stderr, flush=True)
        try:
            start = pd.Timestamp.today().normalize() - pd.DateOffset(years=1, months=1)
            px = fdr.DataReader(code, start=start.strftime("%Y-%m-%d"))
            if px is None or px.empty or "Close" not in px.columns:
                rows.append({"company": name, "code": code, "current_price": None, "current_date": None, "ret_1w": None, "ret_1m": None, "ret_3m": None, "ret_1y": None})
                continue
            px = px.reset_index().rename(columns={px.reset_index().columns[0]: "Date"})
            px["Date"] = pd.to_datetime(px["Date"]).dt.normalize()
            px = px.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")
            latest_date = px["Date"].iloc[-1]
            latest_close = float(px["Close"].iloc[-1])

            rec = {"company": name, "code": code, "current_price": latest_close, "current_date": str(latest_date.date())}
            for label, offset in HORIZONS.items():
                base_px = _asof(px, latest_date - offset)
                rec[f"ret_{label}"] = (latest_close / base_px - 1.0) if base_px and base_px > 0 else None
            rows.append(rec)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            rows.append({"company": name, "code": code, "current_price": None, "current_date": None, "ret_1w": None, "ret_1m": None, "ret_3m": None, "ret_1y": None})

    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    n_ok = out["current_price"].notna().sum()
    print(f"Wrote {OUT_CSV}  rows={len(out)}  ok={n_ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
