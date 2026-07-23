"""
버킷 무관 **공통 스냅샷** DataFrame 생성.

- 입력: `ttm_valuation.db` + `ttm_metric_growth.db` + (선행수익) 시세
- 출력 열·순서: `build_stock_snapshot_df` 가 고정 (네 버킷 CSV 동일 스키마)

경기순환·자산·성장 등은 **유니버스(종목 리스트)만** 갈라서 이 모듈을 호출한 뒤 CSV 로 저장하면 된다.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis.series_per import stock_code_for_company
from scripts.analysis.ttm_valuation_df import load_ttm_valuation_df
from scripts.snapshot_export.stock_snapshot_paths import DEFAULT_GROWTH_DB

GROWTH_GEOM_KEYS: tuple[str, ...] = (
    "rev_geom_1y_mcum",
    "rev_geom_2y_mcum",
    "rev_geom_4y_mcum",
    "op_geom_1y_mcum",
    "op_geom_2y_mcum",
    "op_geom_4y_mcum",
    "ni_geom_1y_mcum",
    "ni_geom_2y_mcum",
    "ni_geom_4y_mcum",
    "capex_geom_1y_mcum",
    "capex_geom_2y_mcum",
    "capex_geom_4y_mcum",
    "cfo_geom_1y_mcum",
    "cfo_geom_2y_mcum",
    "cfo_geom_4y_mcum",
    "fcf_geom_1y_mcum",
    "fcf_geom_2y_mcum",
    "fcf_geom_4y_mcum",
)

GROWTH_GEOM_KEYS_PL: tuple[str, ...] = GROWTH_GEOM_KEYS[:9]
GROWTH_GEOM_KEYS_CF: tuple[str, ...] = GROWTH_GEOM_KEYS[9:]


def _growth_real(v: object) -> float:
    if v is None:
        return float("nan")
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return f if np.isfinite(f) else float("nan")


def load_growth_metrics_for_company(
    company: str, growth_db: Path
) -> dict[str, dict[str, float]] | None:
    """분기당 첫 batch 행만 — rev/op/ni/capex/cfo/fcf 의 1y·2y·4y geom %(ttm_metric_growth_series)."""
    if not growth_db.is_file():
        return None
    cols = ", ".join(GROWTH_GEOM_KEYS)
    con = sqlite3.connect(growth_db)
    try:
        cur = con.execute(
            f"""
            SELECT ttm_end_term, {cols}
            FROM ttm_metric_growth_series
            WHERE company = ?
            ORDER BY ttm_end_term, batch_label
            """,
            (company,),
        )
        by_term: dict[str, dict[str, float]] = {}
        for row in cur.fetchall():
            te = str(row[0])
            if te in by_term:
                continue
            by_term[te] = {
                k: _growth_real(row[i + 1]) for i, k in enumerate(GROWTH_GEOM_KEYS)
            }
    finally:
        con.close()
    return by_term if by_term else None


def _last_trade_on_or_before(px: pd.DataFrame, d: pd.Timestamp) -> pd.Timestamp | None:
    sub = px.loc[px["Date"] <= pd.Timestamp(d).normalize()]
    if sub.empty:
        return None
    return pd.Timestamp(sub["Date"].iloc[-1])


def _close_on(px: pd.DataFrame, d: pd.Timestamp) -> float | None:
    hit = px.loc[px["Date"] == d, "Close"]
    if hit.empty:
        return None
    v = float(hit.iloc[0])
    return v if np.isfinite(v) else None


def _load_px(code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
    try:
        import FinanceDataReader as fdr
    except ImportError:
        print("FinanceDataReader 필요: pip install finance-datareader", file=sys.stderr)
        return None
    raw = fdr.DataReader(code, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
    if raw is None or raw.empty:
        return None
    out = raw.reset_index()
    date_col = "Date" if "Date" in out.columns else out.columns[0]
    out = out.rename(columns={date_col: "Date"})
    if "Close" not in out.columns:
        return None
    out["Date"] = pd.to_datetime(out["Date"]).dt.normalize()
    return out.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")


def _float_field(row: pd.Series, key: str) -> float:
    v = row.get(key)
    if v is None:
        return float("nan")
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return f if np.isfinite(f) else float("nan")


def _forward_returns(
    px: pd.DataFrame,
    entry_d: pd.Timestamp,
    entry_px: float,
    months_list: list[int],
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for m in months_list:
        key = f"ret_{m}m"
        target = entry_d + pd.DateOffset(months=m)
        exit_d = _last_trade_on_or_before(px, target)
        if exit_d is None or exit_d <= entry_d:
            out[key] = None
            continue
        exit_px = _close_on(px, exit_d)
        if exit_px is None or entry_px <= 0:
            out[key] = None
        else:
            out[key] = exit_px / entry_px - 1.0
    return out


def snapshot_column_order(forward_months: list[int]) -> list[str]:
    """CSV·DataFrame 열 순서 (스키마 단일 근거)."""
    ret_keys = [f"ret_{m}m" for m in forward_months]
    return [
        "company",
        "ttm_end_term",
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
        "per_fcf_4y",
        "per_fcf_20d",
        *list(GROWTH_GEOM_KEYS),
        *ret_keys,
    ]


def build_stock_snapshot_df(
    company: str,
    *,
    db_path: Path,
    growth_db: Path | None = None,
    min_quarters: int = 0,
    forward_months: list[int] | None = None,
    anchor_term: str | None = None,
    computed_at: str | None = None,
) -> tuple[pd.DataFrame, str | None]:
    """
    한 종목의 분기별 스냅샷 표. 성공 시 (df, None), 실패 시 (빈 df, 짧은 reason 코드).
    """
    if forward_months is None:
        forward_months = [12, 15, 18]

    df = load_ttm_valuation_df(
        company, db_path=db_path, anchor_term=anchor_term, computed_at=computed_at
    )
    if df.empty:
        return pd.DataFrame(), "no_ttm_rows"

    code = stock_code_for_company(company)
    if not code:
        return pd.DataFrame(), "no_listing_code"

    dates: list[pd.Timestamp] = []
    for _, row in df.iterrows():
        s = row.get("per_anchor_trade_date")
        if s is None or (isinstance(s, float) and np.isnan(s)):
            continue
        try:
            dates.append(pd.to_datetime(str(s).strip()[:10]))
        except (ValueError, TypeError):
            pass
    if not dates:
        return pd.DataFrame(), "no_anchor_dates"

    start = min(dates) - pd.DateOffset(months=1)
    end = max(dates) + pd.DateOffset(months=max(forward_months) + 2)
    px = _load_px(code, start, end)
    if px is None or px.empty:
        return pd.DataFrame(), "price_load_failed"

    gpath = growth_db if growth_db is not None else DEFAULT_GROWTH_DB
    growth_by_term = load_growth_metrics_for_company(company, gpath)

    rows: list[dict] = []
    for i in range(len(df)):
        row = df.iloc[i]
        te = row.get("ttm_end_term", "")

        if i < min_quarters:
            continue

        trade_s = row.get("per_anchor_trade_date")
        entry_px = row.get("per_anchor_close")
        if trade_s is None or entry_px is None:
            continue
        try:
            entry_d = pd.to_datetime(str(trade_s).strip()[:10])
            ep = float(entry_px)
        except (ValueError, TypeError):
            continue
        if not np.isfinite(ep) or ep <= 0:
            continue

        rets = _forward_returns(px, entry_d, ep, forward_months)

        per_ni_4y = _float_field(row, "per_4y_mean")
        per_ni_20d = _float_field(row, "per_20d_mean")
        per_op_4y = _float_field(row, "per_op_4y_mean")
        per_op_20d = _float_field(row, "per_op_20d_mean")
        per_rev_4y = _float_field(row, "per_rev_4y_mean")
        per_rev_20d = _float_field(row, "per_rev_20d_mean")
        per_fcf_4y = _float_field(row, "per_fcf_4y_mean")
        per_fcf_20d = _float_field(row, "per_fcf_20d_mean")

        te_s = str(te).strip() if te is not None else ""
        gm = growth_by_term.get(te_s) if growth_by_term and te_s else None

        rec: dict[str, object] = {
            "company": company,
            "ttm_end_term": te,
            "per_anchor_trade_date": str(trade_s)[:10],
            "per_anchor_close": ep,
            "face_value_end": _float_field(row, "face_value_end"),
            "op_ps": _float_field(row, "op_ps"),
            "ni_parent_ps": _float_field(row, "ni_parent_ps"),
            "capex_ps": _float_field(row, "capex_ps"),
            "cfo_ps": _float_field(row, "cfo_ps"),
            "fcf_ps": _float_field(row, "fcf_ps"),
            "per_ni_4y": per_ni_4y,
            "per_ni_20d": per_ni_20d,
            "per_op_4y": per_op_4y,
            "per_op_20d": per_op_20d,
            "per_rev_4y": per_rev_4y,
            "per_rev_20d": per_rev_20d,
            "per_fcf_4y": per_fcf_4y,
            "per_fcf_20d": per_fcf_20d,
        }
        for k in GROWTH_GEOM_KEYS:
            rec[k] = float(gm[k]) if gm else float("nan")
        rec.update(rets)
        rows.append(rec)

    out_df = pd.DataFrame(rows)
    if not out_df.empty:
        base = snapshot_column_order(forward_months)
        out_df = out_df.reindex(columns=[c for c in base if c in out_df.columns])
    return out_df, None


def write_universe_snapshot_csv(
    names: list[str],
    out_path: Path,
    *,
    db_path: Path,
    growth_db: Path | None,
    min_quarters: int,
    forward_months: list[int],
    anchor_term: str | None,
    computed_at: str | None,
    sleep_sec: float = 0.0,
) -> tuple[int, int, list[tuple[str, str]]]:
    """
    종목 리스트마다 `build_stock_snapshot_df` 호출 후 한 CSV로 합친다.
    반환: (행 수, 성공 종목 수, [(company, reason), ...]).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    parts: list[pd.DataFrame] = []
    skipped: list[tuple[str, str]] = []
    n = len(names)
    for i, co in enumerate(names, 1):
        print(f"[{i}/{n}] {co}", file=sys.stderr, flush=True)
        part, err = build_stock_snapshot_df(
            co,
            db_path=db_path,
            growth_db=growth_db,
            min_quarters=min_quarters,
            forward_months=forward_months,
            anchor_term=anchor_term,
            computed_at=computed_at,
        )
        if err:
            skipped.append((co, err))
        if not part.empty:
            parts.append(part)
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    merged = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    merged.to_csv(out_path, index=False)
    return len(merged), len(parts), skipped
