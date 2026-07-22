"""버킷 공통 신호 계산 — per_ratio(영업이익 우선 폴백, value용)·KOSPI200 대비 alpha·리포트 테이블 헬퍼."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

BENCHMARK_CODE = "KS200"  # KOSPI200 지수(ETF 아님, FDR 지수 코드) — collect_prices.py와 동일 코드


def load_pit_eligible_panel(panel_csv: Path, pit_db: Path, bucket_col: str) -> pd.DataFrame:
    """mcap200_factor_panel.csv ⋈ pit_buckets{N}, {bucket_col}==1 인 (company, ttm_end_term)만.

    테이블명의 N은 bucket_col 끝의 숫자에서 그대로 가져온다 (예: growth_pit28 → pit_buckets28,
    build_pit_buckets.py --min-q 28로 생성). naive 버킷 CSV(오늘 통과 종목의 전체 히스토리)와
    달리, 과거 특정 분기에만 조건을 만족했던 종목의 이벤트도 포함된다 — 생존편향 교정판.
    """
    n = re.search(r"(\d+)$", bucket_col).group(1)
    table = f"pit_buckets{n}"
    panel = pd.read_csv(panel_csv)
    con = sqlite3.connect(pit_db)
    pit = pd.read_sql(f"SELECT company, ttm_end_term, {bucket_col} FROM {table}", con)
    con.close()
    merged = panel.merge(pit, on=["company", "ttm_end_term"], how="inner")
    return merged[merged[bucket_col] == 1].copy()


def compute_per_ratio(df: pd.DataFrame) -> pd.Series:
    """per_ratio = 20일 PER / 4년 평균 PER, op → ni → rev 순 폴백.

    각 분모(4y)가 0 이하이거나 결측이면 다음 우선순위로 넘어간다.
    (selection_strategy.md 정의와 동일: op_20d/op_4y 우선.)
    """
    ratio = pd.Series(float("nan"), index=df.index, dtype="float64")
    for pair_20d, pair_4y in (("per_op_20d", "per_op_4y"), ("per_ni_20d", "per_ni_4y"), ("per_rev_20d", "per_rev_4y")):
        need = ratio.isna()
        denom = df[pair_4y]
        usable = need & denom.notna() & (denom > 0) & df[pair_20d].notna()
        ratio.loc[usable] = df.loc[usable, pair_20d] / df.loc[usable, pair_4y]
    return ratio


def compute_accel(df: pd.DataFrame, num: str = "op_geom_1y_mcum", den: str = "op_geom_4y_mcum") -> pd.Series:
    """acceleration = num/den, den <= 0 이거나 결측이면 NaN (4y 성장이 마이너스면 배율 의미 없음)."""
    accel = pd.Series(float("nan"), index=df.index, dtype="float64")
    usable = df[den].notna() & (df[den] > 0) & df[num].notna()
    accel.loc[usable] = df.loc[usable, num] / df.loc[usable, den]
    return accel


def load_benchmark_prices(prices_db: Path) -> pd.Series:
    """KOSPI200 지수(KS200) 일별 종가 — index=Timestamp 오름차순, S&P500 대비 alpha의 KR 상응 벤치마크."""
    con = sqlite3.connect(prices_db)
    try:
        df = pd.read_sql(
            "SELECT date, close FROM daily_prices WHERE code = ? ORDER BY date",
            con,
            params=(BENCHMARK_CODE,),
        )
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["close"]


def _asof_price(bench: pd.Series, d: pd.Timestamp) -> float | None:
    """d 이전(포함) 마지막 거래일 종가. d가 시계열 시작보다 이르면 None."""
    idx = bench.index.searchsorted(d, side="right") - 1
    if idx < 0:
        return None
    return float(bench.iloc[idx])


def add_benchmark_alpha(
    df: pd.DataFrame, prices_db: Path, months_list: tuple[int, ...] = (12, 15, 18)
) -> pd.DataFrame:
    """`ret_{m}m` 옆에 `alpha_{m}m` = 종목 수익률 − 동일 앵커일 KOSPI200 수익률을 추가.

    US(alpha vs SPY)와 동일한 원칙: 앵커일(`per_anchor_trade_date`) 매수 가정으로
    KOSPI200도 같은 진입일 기준 N개월 후 수익률을 구해 뺀다.
    """
    bench = load_benchmark_prices(prices_db)
    out = df.copy()
    entry_dates = pd.to_datetime(out["per_anchor_trade_date"])

    unique_entries = entry_dates.dropna().unique()
    entry_price_map = {d: _asof_price(bench, pd.Timestamp(d)) for d in unique_entries}
    bench_entry_px = entry_dates.map(entry_price_map)

    for m in months_list:
        ret_col = f"ret_{m}m"
        if ret_col not in out.columns:
            continue
        target_dates = entry_dates + pd.DateOffset(months=m)
        unique_targets = target_dates.dropna().unique()
        exit_price_map = {d: _asof_price(bench, pd.Timestamp(d)) for d in unique_targets}
        bench_exit_px = target_dates.map(exit_price_map)

        bench_ret = pd.Series(float("nan"), index=out.index)
        usable = bench_entry_px.notna() & (bench_entry_px > 0) & bench_exit_px.notna()
        bench_ret.loc[usable] = bench_exit_px[usable] / bench_entry_px[usable] - 1.0

        out[f"alpha_{m}m"] = out[ret_col] - bench_ret
    return out


def bucket_stats(df: pd.DataFrame, mask: pd.Series, ret_col: str = "ret_12m") -> dict:
    """ret_col은 CSV에 소수(0.378=+37.8%)로 저장돼 있음 — 여기서 %로 환산."""
    sub = df.loc[mask & df[ret_col].notna(), ret_col] * 100
    n = len(sub)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "pos": None, "gt20": None, "ltm20": None}
    return {
        "n": n,
        "mean": sub.mean(),
        "median": sub.median(),
        "pos": (sub > 0).mean() * 100,
        "gt20": (sub > 20).mean() * 100,
        "ltm20": (sub < -20).mean() * 100,
    }


def print_stats_table(rows: list[tuple[str, dict]]) -> None:
    header = f"{'구간':<28}{'n':>6}{'mean':>9}{'median':>9}{'>0%':>7}{'>+20%':>7}{'<-20%':>7}"
    print(header)
    print("-" * len(header))
    for label, s in rows:
        if s["n"] == 0:
            print(f"{label:<28}{0:>6}{'—':>9}{'—':>9}{'—':>7}{'—':>7}{'—':>7}")
            continue
        print(
            f"{label:<28}{s['n']:>6}{s['mean']:>8.1f}%{s['median']:>8.1f}%"
            f"{s['pos']:>6.0f}%{s['gt20']:>6.0f}%{s['ltm20']:>6.0f}%"
        )
