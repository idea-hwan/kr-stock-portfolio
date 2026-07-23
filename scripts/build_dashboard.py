"""
대형 성장주·밸류주 대시보드 — mcap200 전체 종목 테이블 + 확정 신호 4개 판단로직.

us-stock-portfolio의 build_dashboard.py와 같은 원칙 — 순수 Python이 정적 HTML 1개를
만든다. Jinja2·React·차트 라이브러리·외부 CDN 전부 없음(인라인 CSS/JS만, 오프라인 동작).
메인 화면도 미국 쪽과 동일하게 "전체 종목 다 넣고, 버킷 미소속(미분류)도 표시, 매수/매도
신호만 버킷 소속 종목에 한정" 원칙을 따른다(2026-07-23 미국 저장소 확인 결과).

방법론 카드의 백테스트 숫자는 미국 쪽처럼 손으로 박아넣지 않고, 이 스크립트가 매번
signal_common.py로 raw/alpha를 직접 재계산해서 채운다(stale 방지, 2026-07-23 성장주
문서에서 겪은 문제 재발 방지).

출력: docs/index.html
실행: .venv/bin/python scripts/build_dashboard.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.simulate.signal_common import (
    add_benchmark_alpha,
    bucket_stats,
    compute_accel,
    compute_per_ratio,
    load_pit_eligible_panel,
)

PANEL_CSV = _ROOT / "data" / "analytics" / "mcap200_factor_panel.csv"
PIT_DB = _ROOT / "data" / "analytics" / "pit_buckets.db"
PRICES_DB = _ROOT / "data" / "analytics" / "prices.db"
MCAP_CSV = _ROOT / "stock_data" / "mcap_top_200.csv"
INDUSTRY_CSV = _ROOT / "data" / "analytics" / "industry_map.csv"
CURRENT_PRICE_CSV = _ROOT / "data" / "analytics" / "current_prices.csv"
OUT_HTML = _ROOT / "docs" / "index.html"

MEGA_CAP_NAMES = ("삼성전자", "SK하이닉스")


# ── 방법론 카드용 백테스트 계산 (기존 v1) ──────────────────────────────────────

def _stat_pair(df: pd.DataFrame, mask: pd.Series, ret_col: str, alpha_col: str) -> dict:
    r = bucket_stats(df, mask, ret_col=ret_col)
    a = bucket_stats(df, mask, ret_col=alpha_col)
    return {"n": r["n"], "raw_mean": r["mean"], "raw_median": r["median"], "alpha_mean": a["mean"], "alpha_median": a["median"]}


def compute_growth_signals() -> dict:
    df = load_pit_eligible_panel(PANEL_CSV, PIT_DB, "growth_pit16")
    df = add_benchmark_alpha(df, PRICES_DB, months_list=(3, 6, 9, 12))
    df["per_ratio"] = compute_per_ratio(df)
    df["accel"] = compute_accel(df)

    buy_mask = (df["per_ratio"] >= 0.5) & (df["per_ratio"] < 1.0) & (df["accel"] >= 2) & (df["accel"] < 5)
    sell_mask = (
        df["ni_geom_1y_mcum"].notna() & (df["ni_geom_1y_mcum"] < 0)
        & df["cfo_geom_1y_mcum"].notna() & (df["cfo_geom_1y_mcum"] < 0)
        & df["per_ni_4y"].notna() & (df["per_ni_4y"] > 0)
        & df["per_ni_20d"].notna() & (df["per_ni_20d"] > 0)
        & (df["per_ni_20d"] / df["per_ni_4y"] > 1.25)
    )
    baseline = pd.Series(True, index=df.index)

    return {
        "universe_n": int(df["company"].nunique()),
        "events_n": len(df),
        "term_range": (str(df["ttm_end_term"].min()), str(df["ttm_end_term"].max())),
        "baseline_12m": _stat_pair(df, baseline, "ret_12m", "alpha_12m"),
        "buy": {m: _stat_pair(df, buy_mask, f"ret_{m}m", f"alpha_{m}m") for m in (12,)},
        "sell": {m: _stat_pair(df, sell_mask, f"ret_{m}m", f"alpha_{m}m") for m in (3, 6, 9, 12)},
    }


def compute_value_signals() -> dict:
    df = load_pit_eligible_panel(PANEL_CSV, PIT_DB, "value_pit16")
    df = add_benchmark_alpha(df, PRICES_DB, months_list=(3, 6, 9, 12))
    df["per_ratio"] = compute_per_ratio(df)

    buy_mask = (df["per_ratio"] < 0.5) & df["op_geom_1y_mcum"].notna() & (df["op_geom_1y_mcum"] > 0)
    sell_mask = (
        df["ni_geom_1y_mcum"].notna() & (df["ni_geom_1y_mcum"] < 0)
        & df["cfo_geom_1y_mcum"].notna() & (df["cfo_geom_1y_mcum"] < 0)
        & df["per_ni_4y"].notna() & (df["per_ni_4y"] > 0)
        & df["per_ni_20d"].notna() & (df["per_ni_20d"] > 0)
        & (df["per_ni_20d"] / df["per_ni_4y"] > 1.25)
    )
    baseline = pd.Series(True, index=df.index)

    return {
        "universe_n": int(df["company"].nunique()),
        "events_n": len(df),
        "term_range": (str(df["ttm_end_term"].min()), str(df["ttm_end_term"].max())),
        "baseline_12m": _stat_pair(df, baseline, "ret_12m", "alpha_12m"),
        "buy": {m: _stat_pair(df, buy_mask, f"ret_{m}m", f"alpha_{m}m") for m in (12,)},
        "sell": {m: _stat_pair(df, sell_mask, f"ret_{m}m", f"alpha_{m}m") for m in (3, 6, 9, 12)},
    }


def compute_benchmark_note() -> dict:
    """벤치마크(KOSPI200) 집중도 — 매번 라이브로 재계산해서 stale 방지."""
    mcap = pd.read_csv(MCAP_CSV, dtype={"Code": str})
    total = mcap["Marcap"].sum()
    mega = mcap[mcap["Name"].isin(MEGA_CAP_NAMES)]["Marcap"].sum()
    weight_pct = mega / total * 100 if total else None

    returns = {}
    con = sqlite3.connect(PRICES_DB)
    try:
        for code, name in (("005930", "삼성전자"), ("000660", "SK하이닉스")):
            df = pd.read_sql("SELECT date, close FROM daily_prices WHERE code = ? ORDER BY date", con, params=(code,))
            if df.empty:
                continue
            df["date"] = pd.to_datetime(df["date"])
            end_d = df["date"].max()
            start_target = end_d - pd.DateOffset(months=12)
            start_row = df.iloc[(df["date"] - start_target).abs().argsort()[:1]]
            end_row = df.iloc[[-1]]
            ret = end_row["close"].values[0] / start_row["close"].values[0] - 1.0
            returns[name] = {
                "ret_12m_pct": ret * 100,
                "start_date": str(start_row["date"].values[0])[:10],
                "end_date": str(end_row["date"].values[0])[:10],
            }
    finally:
        con.close()

    return {"mega_cap_weight_pct": weight_pct, "returns": returns}


# ── 메인 테이블용: 종목별 최신 분기 스냅샷 + 현재 신호 판정 ──────────────────────

def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def compute_stock_rows() -> list[dict]:
    panel = pd.read_csv(PANEL_CSV)
    latest = panel.sort_values("ttm_end_term").groupby("company", as_index=False).tail(1).copy()

    con = sqlite3.connect(PIT_DB)
    pit = pd.read_sql("SELECT company, ttm_end_term, growth_pit16, value_pit16 FROM pit_buckets16", con)
    con.close()
    latest = latest.merge(pit, on=["company", "ttm_end_term"], how="left")
    latest["growth_pit16"] = latest["growth_pit16"].fillna(0).astype(int)
    latest["value_pit16"] = latest["value_pit16"].fillna(0).astype(int)

    mcap = pd.read_csv(MCAP_CSV, dtype={"Code": str})
    latest = latest.merge(mcap[["Code", "Name", "Marcap"]], left_on="company", right_on="Name", how="left")

    if INDUSTRY_CSV.is_file():
        industry = pd.read_csv(INDUSTRY_CSV)[["company", "industry"]]
        latest = latest.merge(industry, on="company", how="left")
    else:
        latest["industry"] = None

    # 주의: mcap200_factor_panel.csv에 이미 ret_3m/6m/9m/12m/15m/18m(미래 forward 수익률)이
    # 있어서, current_prices.csv의 trailing(후행) ret_3m 등과 이름이 겹치면 병합 시
    # ret_3m_x/ret_3m_y로 쪼개져 조용히 사라진다 — trailing_* 로 이름을 바꿔서 충돌을 없앤다.
    if CURRENT_PRICE_CSV.is_file():
        cur = pd.read_csv(CURRENT_PRICE_CSV)[["company", "current_price", "current_date", "ret_1w", "ret_1m", "ret_3m", "ret_1y"]]
        cur = cur.rename(columns={"ret_1w": "trailing_1w", "ret_1m": "trailing_1m", "ret_3m": "trailing_3m", "ret_1y": "trailing_1y"})
        latest = latest.merge(cur, on="company", how="left")
    else:
        for c in ("current_price", "current_date", "trailing_1w", "trailing_1m", "trailing_3m", "trailing_1y"):
            latest[c] = None

    latest["per_ratio"] = compute_per_ratio(latest)
    latest["accel"] = compute_accel(latest)

    rows: list[dict] = []
    for _, r in latest.iterrows():
        is_growth = r["growth_pit16"] == 1
        is_value = r["value_pit16"] == 1
        bucket_labels = []
        if is_growth:
            bucket_labels.append("성장")
        if is_value:
            bucket_labels.append("밸류")
        bucket = "+".join(bucket_labels) if bucket_labels else "미분류"

        per_ratio = _num(r["per_ratio"])
        accel = _num(r["accel"])
        op_1y = _num(r["op_geom_1y_mcum"])
        op_2y = _num(r["op_geom_2y_mcum"])
        ni_1y = _num(r["ni_geom_1y_mcum"])
        cfo_1y = _num(r["cfo_geom_1y_mcum"])
        per_ni_20d = _num(r["per_ni_20d"])
        per_ni_4y = _num(r["per_ni_4y"])
        pni_ratio = per_ni_20d / per_ni_4y if (per_ni_20d is not None and per_ni_4y and per_ni_4y > 0 and per_ni_20d > 0) else None

        sell_cond = ni_1y is not None and ni_1y < 0 and cfo_1y is not None and cfo_1y < 0 and pni_ratio is not None and pni_ratio > 1.25

        buy_labels, sell_labels = [], []
        if is_growth:
            if per_ratio is not None and 0.5 <= per_ratio < 1.0 and accel is not None and 2 <= accel < 5:
                buy_labels.append("성장매수")
            if sell_cond:
                sell_labels.append("성장매도")
        if is_value:
            if per_ratio is not None and per_ratio < 0.5 and op_1y is not None and op_1y > 0:
                buy_labels.append("밸류매수")
            if sell_cond:
                sell_labels.append("밸류매도")

        if op_1y is None:
            trend = "—"
        elif op_1y > 0:
            trend = "▲▲ 가속" if (accel is not None and accel >= 2) else "▲ 성장"
        else:
            trend = "▼▼ 2y역성장" if (op_2y is not None and op_2y < 0) else "▼ 역성장"

        if per_ratio is None:
            valuation_tag = "—"
        elif per_ratio < 0.9:
            valuation_tag = "저평가"
        elif per_ratio > 1.25:
            valuation_tag = "고평가"
        else:
            valuation_tag = "—"

        op_ps, ni_ps, cfo_ps, fcf_ps = _num(r["op_ps"]), _num(r["ni_parent_ps"]), _num(r["cfo_ps"]), _num(r["fcf_ps"])
        cur_price = _num(r.get("current_price"))

        def _cur_ratio(ps: float | None) -> float | None:
            return cur_price / ps if (cur_price is not None and ps is not None and ps > 0) else None

        rows.append(
            {
                "company": r["company"],
                "code": r.get("Code") if pd.notna(r.get("Code")) else None,
                "industry": r.get("industry") if pd.notna(r.get("industry")) else None,
                "bucket": bucket,
                "marcap": _num(r.get("Marcap")),
                "ttm_end_term": r["ttm_end_term"],
                "anchor_date": r["per_anchor_trade_date"] if pd.notna(r["per_anchor_trade_date"]) else None,
                "anchor_close": _num(r["per_anchor_close"]),
                "current_price": cur_price,
                "current_date": r.get("current_date") if pd.notna(r.get("current_date")) else None,
                "ret_1w": _num(r.get("trailing_1w")), "ret_1m": _num(r.get("trailing_1m")),
                "ret_3m": _num(r.get("trailing_3m")), "ret_1y": _num(r.get("trailing_1y")),
                "per_op_20d": _num(r["per_op_20d"]), "per_op_4y": _num(r["per_op_4y"]), "per_op_now": _cur_ratio(op_ps),
                "per_ni_20d": per_ni_20d, "per_ni_4y": per_ni_4y, "per_ni_now": _cur_ratio(ni_ps),
                "per_rev_20d": _num(r["per_rev_20d"]), "per_rev_4y": _num(r["per_rev_4y"]),
                "per_fcf_20d": _num(r["per_fcf_20d"]), "per_fcf_4y": _num(r["per_fcf_4y"]), "per_fcf_now": _cur_ratio(fcf_ps),
                "op_ps": op_ps, "ni_ps": ni_ps, "cfo_ps": cfo_ps, "fcf_ps": fcf_ps,
                "rev_1y": _num(r["rev_geom_1y_mcum"]), "rev_2y": _num(r["rev_geom_2y_mcum"]), "rev_4y": _num(r["rev_geom_4y_mcum"]),
                "op_1y": op_1y, "op_2y": op_2y, "op_4y": _num(r["op_geom_4y_mcum"]),
                "ni_1y": ni_1y, "ni_2y": _num(r["ni_geom_2y_mcum"]), "ni_4y": _num(r["ni_geom_4y_mcum"]),
                "fcf_1y": _num(r["fcf_geom_1y_mcum"]), "fcf_2y": _num(r["fcf_geom_2y_mcum"]), "fcf_4y": _num(r["fcf_geom_4y_mcum"]),
                "capex_1y": _num(r["capex_geom_1y_mcum"]), "capex_2y": _num(r["capex_geom_2y_mcum"]), "capex_4y": _num(r["capex_geom_4y_mcum"]),
                "cfo_1y": cfo_1y,
                "trend": trend,
                "valuation_tag": valuation_tag,
                "buy": ",".join(buy_labels) or None,
                "sell": ",".join(sell_labels) or None,
            }
        )
    rows.sort(key=lambda x: (x["marcap"] is None, -(x["marcap"] or 0)))
    return rows


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.1f}%"


def _signal_card(title: str, plain: str, formula: str, sig: dict, horizons: list[int], total_events: int) -> str:
    rows = []
    for m in horizons:
        s = sig[m]
        pct = s["n"] / total_events * 100 if total_events else 0.0
        rows.append(
            f"<tr><td>{m}m</td><td>{s['n']} <span class=\"sub\">(전체의 {pct:.1f}%)</span></td>"
            f"<td class=\"num\">{_fmt_pct(s['raw_mean'])} / {_fmt_pct(s['raw_median'])}</td>"
            f"<td class=\"num\">{_fmt_pct(s['alpha_mean'])} / {_fmt_pct(s['alpha_median'])}</td></tr>"
        )
    return f"""
    <div class="card">
      <h3>{title}</h3>
      <p class="plain">{plain}</p>
      <p class="formula">{formula}</p>
      <table>
        <thead><tr><th>기간</th><th>n (해당 비중)</th><th>raw mean/median</th><th>alpha mean/median</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>한국 주식 대시보드</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {
  --bg: #0d1117; --panel: #161b22; --border: #30363d;
  --text: #e6edf3; --sub: #8b949e; --pos: #3fb950; --neg: #f85149; --accent: #58a6ff;
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font-family: -apple-system, "Pretendard", "Malgun Gothic", sans-serif; }
.wrap { max-width: min(1900px, 96vw); margin: 0 auto; padding: 24px 20px 80px; }
h1 { font-size: 20px; margin: 0 0 4px; }
.meta { color: var(--sub); font-size: 12px; margin: 0 0 6px; }
h2 { font-size: 16px; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-top: 40px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
@media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px 18px; }
.card h3 { margin: 0 0 6px; font-size: 14px; }
.plain { font-size: 13px; color: var(--text); margin: 0 0 8px; line-height: 1.6; }
.formula { font-size: 11px; color: var(--sub); font-family: monospace; margin: 0 0 10px; line-height:1.5; background: rgba(255,255,255,0.03); padding: 6px 8px; border-radius: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { padding: 6px 8px; text-align: right; border-bottom: 1px solid var(--border); white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
.num { font-variant-numeric: tabular-nums; }
.sub { color: var(--sub); font-size: 10px; }
.note { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px 18px; font-size: 13px; line-height: 1.7; margin-top: 16px; }
.note b { color: var(--accent); }
.baseline { color: var(--sub); font-size: 12px; margin-top: 10px; }
footer { color: var(--sub); font-size: 11px; margin-top: 48px; }
code { font-family: monospace; background: rgba(255,255,255,0.05); padding: 1px 4px; border-radius: 3px; }

.ctrl { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 16px 0; }
.ctrl button { background: var(--panel); border: 1px solid var(--border); color: var(--text); padding: 6px 12px; border-radius: 6px; font-size: 12px; cursor: pointer; }
.ctrl button.active { border-color: var(--accent); color: var(--accent); }
.ctrl input[type=text] { background: var(--panel); border: 1px solid var(--border); color: var(--text); padding: 6px 10px; border-radius: 6px; font-size: 12px; flex: 1; min-width: 140px; }
.ctrl .spacer { flex: 1; }

.tbl-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }
#tbl { min-width: 900px; }
#tbl thead th { position: sticky; top: 0; background: var(--panel); cursor: pointer; user-select: none; }
#tbl thead th:hover { color: var(--accent); }
#tbl tbody tr:not(.dr) { cursor: pointer; }
#tbl tbody tr:not(.dr):hover { background: rgba(255,255,255,0.03); }
.tag { padding: 2px 6px; border-radius: 4px; font-size: 11px; }
.tag.pos { background: rgba(63,185,80,0.15); color: var(--pos); }
.tag.neg { background: rgba(248,81,73,0.15); color: var(--neg); }
.pos-text { color: var(--pos); }
.neg-text { color: var(--neg); }
.ticker { color: var(--accent); font-weight: 600; font-family: monospace; }
#tbl thead th.sorted::after { content: attr(data-arrow); margin-left: 4px; color: var(--accent); }
.dr td { background: rgba(255,255,255,0.02); cursor: default; }
.detail-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0; padding: 4px; text-align: left; }
.dcol { border-right: 1px solid var(--border); padding: 14px 16px; }
.dcol:last-child { border-right: none; }
.dcol h4 { margin: 0 0 8px; font-size: 11px; color: var(--accent); text-transform: none; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.dcol h4:not(:first-child) { margin-top: 14px; }
.irow { display: flex; justify-content: space-between; font-size: 12px; padding: 3px 0; gap: 8px; }
.dtbl { width: 100%; font-size: 12px; margin-bottom: 4px; }
.dtbl th, .dtbl td { padding: 3px 4px; }
.dtbl th:first-child, .dtbl td:first-child { text-align: left; color: var(--sub); }
.hidden { display: none; }
</style>
</head>
<body>
<div class="wrap">
  <h1>한국 주식 대시보드</h1>
  <p class="meta">가격 기준: __PRICE_DATE__ &nbsp;|&nbsp; 재무 기준: 종목별 최신 분기(__LATEST_TERM__) &nbsp;|&nbsp; __STOCK_N__종목</p>

  <div class="ctrl">
    <button data-bucket="all" class="bfilter active">전체</button>
    <button data-bucket="성장" class="bfilter">성장</button>
    <button data-bucket="밸류" class="bfilter">밸류</button>
    <button data-bucket="미분류" class="bfilter">미분류</button>
    <button data-signal="buy" class="sfilter">매수 신호만</button>
    <button data-signal="sell" class="sfilter">매도 신호만</button>
    <input type="text" id="search" placeholder="종목명 검색...">
    <span class="spacer"></span>
    <button id="toggle-logic">판단로직 보기</button>
  </div>

  <div id="main-view">
    <div class="tbl-wrap">
      <table id="tbl">
        <thead>
          <tr>
            <th>#</th>
            <th data-key="code">코드</th>
            <th data-key="company">종목명</th>
            <th data-key="bucket">버킷</th>
            <th data-key="marcap">시총(억원)</th>
            <th data-key="current_price">현재가</th>
            <th data-key="per_op_20d">P/OP(20d)</th>
            <th data-key="per_op_4y">P/OP(4y)</th>
            <th data-key="trend">이익 추세</th>
            <th data-key="valuation_tag">저평가 여부(P/OP)</th>
            <th data-key="buy">매수 신호</th>
            <th data-key="sell">매도 신호</th>
            <th data-key="ret_1w">1주</th>
            <th data-key="ret_1m">1개월</th>
            <th data-key="ret_3m">3개월</th>
            <th data-key="ret_1y">1년</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
    <p class="meta" id="count"></p>
  </div>

  <div id="logic-view" class="hidden">
    <h2>성장주 (growth_pit16 — 영업이익 16분기 연속 흑자, __G_UNIV__종목·__G_EVENTS__이벤트, __G_TERM_START__~__G_TERM_END__)</h2>
    <div class="grid">
      __GROWTH_BUY_CARD__
      __GROWTH_SELL_CARD__
    </div>
    <p class="baseline">baseline(전체) 12m — raw __G_BASE_RAW__ · alpha __G_BASE_ALPHA__</p>

    <h2>밸류주 (value_pit16 — 순이익 16분기 연속 흑자, __V_UNIV__종목·__V_EVENTS__이벤트, __V_TERM_START__~__V_TERM_END__)</h2>
    <div class="grid">
      __VALUE_BUY_CARD__
      __VALUE_SELL_CARD__
    </div>
    <p class="baseline">baseline(전체) 12m — raw __V_BASE_RAW__ · alpha __V_BASE_ALPHA__</p>

    <p class="meta">아래 표의 수익률은 전부 <b>미래(forward) 수익률</b>이다 — 이 조건을 만족한 시점에 실제로
    샀다고 가정하고, 그 이후 3/6/9/12개월 동안 얼마를 벌었는지를 계산한 것이다(과거 추세가 아니다).</p>

    <h2>용어</h2>
    <div class="note gloss">
      <b>per_ratio</b> = 최근 20일 평균 PER ÷ 최근 4년 평균 PER. 1보다 작으면 이 회사가 평소보다
      싸게 거래되고 있다는 뜻, 1보다 크면 평소보다 비싸다는 뜻이다.<br>
      <b>acceleration</b> = 최근 1년 영업이익 성장률 ÷ 최근 4년 평균 성장률. 1보다 크면 최근 성장
      속도가 예전보다 빨라졌다는 뜻이다.<br>
      <b>ni_1y↓ / cfo_1y↓</b> = 순이익 / 영업활동현금흐름이 1년 전보다 줄었다(마이너스 성장)는 표시다.<br>
      <b>기간(3m/6m/9m/12m)</b> = 조건을 만족한 시점에 사서 그만큼의 기간을 들고 있었을 때의
      미래 수익률(forward return) — "그 종목이 이전에 얼마나 올랐는지"가 아니라 "신호가 뜬 뒤
      앞으로 얼마나 올랐는지"다.<br>
      <b>raw</b> = 실제로 번 수익률 그대로. <b>alpha</b> = 그 수익률에서 KOSPI200 지수 수익률을 뺀 값
      — "지수보다 얼마나 더/덜 벌었나"다. <b>n</b> = 이 조건을 만족했던 (종목·분기) 사례 수, 괄호 안은
      같은 버킷 전체 이벤트 대비 비중(이 조건이 얼마나 자주 나타나는지).
    </div>

    <h2>벤치마크(KOSPI200) 유의사항</h2>
    <div class="note">
      삼성전자·SK하이닉스가 mcap200 시총의 <b>__MEGA_WEIGHT__%</b>를 차지한다(__MEGA_RET_1__, __MEGA_RET_2__).
      이 두 종목이 급등하면 KOSPI200 자체가 밀려 올라가면서, 위 alpha 지표가 실제 손익과 어긋날 수 있다 —
      <b>항상 raw와 alpha를 같이 보고 판단할 것</b>. 두 종목 모두 위 매수 신호를 사실상 못 잡는다(실적
      변동성으로 버킷 이탈/가속도 미충족) — 자세한 배경은 docs/large_growth_selection_strategy.md §7.3,
      docs/large_value_selection_strategy.md §6.2 참고.
    </div>
  </div>

  <footer>
    재현: <code>build_dashboard.py</code> · 신호 정의: docs/large_growth_selection_strategy.md, docs/large_value_selection_strategy.md<br>
    현재가·수익률·업종은 별도 캐시(<code>current_prices.csv</code>·<code>industry_map.csv</code>) — 빌드마다 재조회 안 함. 최신화: <code>build_current_prices.py</code>(매일)·<code>build_industry_map.py</code>(가끔)
  </footer>
</div>
<script>
const STOCKS = __STOCKS_JSON__;
let sortKey = 'marcap', sortDir = -1;
let bucketFilter = 'all', signalFilter = 'all', search = '';
let shown = [];

function fmtPct(v) { return v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%'; }
function fmtPctColor(v) {
  if (v == null) return '<span class="sub">—</span>';
  const cls = v > 0 ? 'pos-text' : (v < 0 ? 'neg-text' : '');
  return `<span class="${cls}">${fmtPct(v)}</span>`;
}
function fmtRatio(a, b) { if (a == null || b == null || b <= 0) return '—'; return (a / b).toFixed(2); }
function fmtRatioVal(v) { return v == null ? '—' : v.toFixed(1); }
function fmtWon(w) { return w == null ? '—' : Math.round(w / 1e8).toLocaleString(); }
function tagHtml(v) {
  if (!v || v === '—') return '<span class="sub">—</span>';
  const cls = v.includes('저평가') ? 'pos-text' : (v.includes('고평가') ? 'neg-text' : '');
  return `<span class="${cls}">${v}</span>`;
}

function getFiltered() {
  return STOCKS.filter(s => {
    if (bucketFilter !== 'all' && !s.bucket.includes(bucketFilter)) return false;
    if (signalFilter === 'buy' && !s.buy) return false;
    if (signalFilter === 'sell' && !s.sell) return false;
    if (search && !s.company.includes(search)) return false;
    return true;
  }).sort((a, b) => {
    let av = a[sortKey];
    let bv = b[sortKey];
    if (typeof av === 'string') { av = av || ''; bv = bv || ''; return av.localeCompare(bv) * sortDir; }
    if (av == null) av = -Infinity;
    if (bv == null) bv = -Infinity;
    return (av - bv) * sortDir;
  });
}

function fmtWonVal(v) { return v == null ? '—' : Math.round(v).toLocaleString() + '원'; }
function fmtNum2(v) { return v == null ? '—' : v.toFixed(1); }
function row3(label, now, d20, y4) {
  return `<tr><td>${label}</td><td class="num">${fmtNum2(now)}</td><td class="num">${fmtNum2(d20)}</td><td class="num">${fmtNum2(y4)}</td></tr>`;
}
function rowCagr(label, y1, y2, y4) {
  return `<tr><td>${label}</td><td class="num">${fmtPctColor(y1)}</td><td class="num">${fmtPctColor(y2)}</td><td class="num">${fmtPctColor(y4)}</td></tr>`;
}
function infoRow(label, val) { return `<div class="irow"><span class="sub">${label}</span><span>${val}</span></div>`; }

function detailHtml(s) {
  return `<div class="detail-grid">
    <div class="dcol">
      <h4>기본 정보</h4>
      ${infoRow('종목코드', s.code || '—')}
      ${infoRow('회사명', s.company)}
      ${infoRow('업종', s.industry || '—')}
      ${infoRow('버킷', s.bucket)}
      ${infoRow('기준분기', s.ttm_end_term)}
      ${infoRow('현재가(' + (s.current_date || '—') + ')', s.current_price != null ? s.current_price.toLocaleString() + '원' : '—')}
      ${infoRow('밸류에이션 기준일', s.anchor_date || '—')}
      ${infoRow('시총(억원)', fmtWon(s.marcap))}
      ${infoRow('이익 추세', s.trend)}
      ${infoRow('저평가 여부(P/OP)', tagHtml(s.valuation_tag))}
      ${infoRow('매수 신호', s.buy ? '<span class="tag pos">' + s.buy + '</span>' : '—')}
      ${infoRow('매도 신호', s.sell ? '<span class="tag neg">' + s.sell + '</span>' : '—')}
    </div>
    <div class="dcol">
      <h4>밸류에이션 — 현재 / 20일 / 4년 평균</h4>
      <table class="dtbl">
        <thead><tr><th></th><th>현재</th><th>20일</th><th>4년</th></tr></thead>
        <tbody>
          ${row3('P/NI', s.per_ni_now, s.per_ni_20d, s.per_ni_4y)}
          ${row3('P/OP', s.per_op_now, s.per_op_20d, s.per_op_4y)}
          ${row3('P/FCF', s.per_fcf_now, s.per_fcf_20d, s.per_fcf_4y)}
        </tbody>
      </table>
      <h4>TTM 재무 (주당)</h4>
      ${infoRow('영업이익', fmtWonVal(s.op_ps))}
      ${infoRow('순이익', fmtWonVal(s.ni_ps))}
      ${infoRow('영업현금흐름', fmtWonVal(s.cfo_ps))}
      ${infoRow('FCF', fmtWonVal(s.fcf_ps))}
    </div>
    <div class="dcol">
      <h4>성장률 CAGR — 연환산(%)</h4>
      <table class="dtbl">
        <thead><tr><th></th><th>1y</th><th>2y</th><th>4y</th></tr></thead>
        <tbody>
          ${rowCagr('매출', s.rev_1y, s.rev_2y, s.rev_4y)}
          ${rowCagr('영업이익', s.op_1y, s.op_2y, s.op_4y)}
          ${rowCagr('순이익', s.ni_1y, s.ni_2y, s.ni_4y)}
          ${rowCagr('FCF', s.fcf_1y, s.fcf_2y, s.fcf_4y)}
          ${rowCagr('CAPEX', s.capex_1y, s.capex_2y, s.capex_4y)}
        </tbody>
      </table>
      <h4>주가 수익률</h4>
      ${infoRow('1주', fmtPctColor(s.ret_1w))}
      ${infoRow('1개월', fmtPctColor(s.ret_1m))}
      ${infoRow('3개월', fmtPctColor(s.ret_3m))}
      ${infoRow('1년', fmtPctColor(s.ret_1y))}
    </div>
  </div>`;
}

function toggleRow(i) {
  const dr = document.getElementById('dr-' + i);
  dr.style.display = dr.style.display === 'none' ? '' : 'none';
}

function renderTable() {
  shown = getFiltered();
  const tbody = document.getElementById('tbody');
  let html = '';
  shown.forEach((s, i) => {
    const bucketCls = s.bucket === '미분류' ? 'sub' : '';
    html += `<tr onclick="toggleRow(${i})">
      <td class="num sub">${i + 1}</td>
      <td class="ticker">${s.code || '—'}</td>
      <td>${s.company}</td>
      <td class="${bucketCls}">${s.bucket}</td>
      <td class="num">${fmtWon(s.marcap)}</td>
      <td class="num">${s.current_price != null ? s.current_price.toLocaleString() : '—'}</td>
      <td class="num">${fmtRatioVal(s.per_op_20d)}</td>
      <td class="num">${fmtRatioVal(s.per_op_4y)}</td>
      <td>${s.trend}</td>
      <td>${tagHtml(s.valuation_tag)}</td>
      <td>${s.buy ? '<span class="tag pos">' + s.buy + '</span>' : '<span class="sub">—</span>'}</td>
      <td>${s.sell ? '<span class="tag neg">' + s.sell + '</span>' : '<span class="sub">—</span>'}</td>
      <td class="num">${fmtPctColor(s.ret_1w)}</td>
      <td class="num">${fmtPctColor(s.ret_1m)}</td>
      <td class="num">${fmtPctColor(s.ret_3m)}</td>
      <td class="num">${fmtPctColor(s.ret_1y)}</td>
    </tr>
    <tr class="dr" id="dr-${i}" style="display:none"><td colspan="16">${detailHtml(s)}</td></tr>`;
  });
  tbody.innerHTML = html;
  document.getElementById('count').textContent = shown.length + '종목 표시 중 (전체 ' + STOCKS.length + '종목)';
}

document.querySelectorAll('.bfilter').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.bfilter').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    bucketFilter = btn.dataset.bucket;
    renderTable();
  });
});
document.querySelectorAll('.sfilter').forEach(btn => {
  btn.addEventListener('click', () => {
    const active = btn.classList.toggle('active');
    document.querySelectorAll('.sfilter').forEach(b => { if (b !== btn) b.classList.remove('active'); });
    signalFilter = active ? btn.dataset.signal : 'all';
    renderTable();
  });
});
document.getElementById('search').addEventListener('input', (e) => {
  search = e.target.value.trim();
  renderTable();
});
function updateSortIndicator() {
  document.querySelectorAll('#tbl thead th').forEach(th => {
    th.classList.remove('sorted');
    if (th.dataset.key === sortKey) {
      th.classList.add('sorted');
      th.dataset.arrow = sortDir === -1 ? '▼' : '▲';
    }
  });
}
document.querySelectorAll('#tbl thead th[data-key]').forEach(th => {
  th.addEventListener('click', () => {
    const key = th.dataset.key;
    if (sortKey === key) { sortDir *= -1; } else { sortKey = key; sortDir = -1; }
    updateSortIndicator();
    renderTable();
  });
});
updateSortIndicator();
document.getElementById('toggle-logic').addEventListener('click', () => {
  const main = document.getElementById('main-view');
  const logic = document.getElementById('logic-view');
  const showingLogic = !logic.classList.contains('hidden');
  logic.classList.toggle('hidden', showingLogic);
  main.classList.toggle('hidden', !showingLogic);
  document.getElementById('toggle-logic').textContent = showingLogic ? '판단로직 보기' : '종목 테이블 보기';
});

renderTable();
</script>
</body>
</html>
"""


def generate_html(g: dict, v: dict, bench: dict, stocks: list[dict]) -> str:
    html = HTML_TEMPLATE

    from datetime import datetime, timezone

    html = html.replace("__GENERATED_AT__", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    html = html.replace("__STOCK_N__", str(len(stocks)))
    latest_term = max((s["ttm_end_term"] for s in stocks), default="—")
    html = html.replace("__LATEST_TERM__", str(latest_term))
    price_dates = [s["current_date"] for s in stocks if s.get("current_date")]
    price_date = max(price_dates) if price_dates else "—"
    html = html.replace("__PRICE_DATE__", str(price_date))
    html = html.replace("__STOCKS_JSON__", json.dumps(stocks, ensure_ascii=False, separators=(",", ":")))

    html = html.replace("__G_UNIV__", str(g["universe_n"])).replace("__G_EVENTS__", str(g["events_n"]))
    html = html.replace("__G_TERM_START__", g["term_range"][0]).replace("__G_TERM_END__", g["term_range"][1])
    html = html.replace(
        "__GROWTH_BUY_CARD__",
        _signal_card(
            "매수",
            "적당히 저평가돼 있고(너무 싸지도, 안 싸지도 않은 구간) 영업이익이 최근 1년 새 4년 평균보다 2~5배 빠르게 늘고 있는 종목",
            "0.5 ≤ per_ratio &lt; 1.0  AND  2 ≤ acceleration &lt; 5",
            g["buy"], [12], g["events_n"],
        ),
    )
    html = html.replace(
        "__GROWTH_SELL_CARD__",
        _signal_card(
            "매도",
            "순이익이 1년 전보다 줄었고, 영업으로 벌어들이는 현금도 줄었는데, 주가는 평소(4년 평균)보다 25% 이상 비싸게 거래되는 종목",
            "ni_1y↓  AND  cfo_1y↓  AND  P/NI 고평가(per_ni_20d/per_ni_4y &gt; 1.25)",
            g["sell"], [3, 6, 9, 12], g["events_n"],
        ),
    )
    gb = g["baseline_12m"]
    html = html.replace("__G_BASE_RAW__", f"mean {_fmt_pct(gb['raw_mean'])} / median {_fmt_pct(gb['raw_median'])}")
    html = html.replace("__G_BASE_ALPHA__", f"mean {_fmt_pct(gb['alpha_mean'])} / median {_fmt_pct(gb['alpha_median'])}")

    html = html.replace("__V_UNIV__", str(v["universe_n"])).replace("__V_EVENTS__", str(v["events_n"]))
    html = html.replace("__V_TERM_START__", v["term_range"][0]).replace("__V_TERM_END__", v["term_range"][1])
    html = html.replace(
        "__VALUE_BUY_CARD__",
        _signal_card(
            "매수",
            "평소(4년 평균)보다 확실히 싸게 거래되고 있고, 영업이익은 1년 전보다 늘어난 종목 — 싸기만 하고 실적이 나빠지는 '가치함정'은 제외",
            "per_ratio &lt; 0.5  AND  op_geom_1y_mcum &gt; 0",
            v["buy"], [12], v["events_n"],
        ),
    )
    html = html.replace(
        "__VALUE_SELL_CARD__",
        _signal_card(
            "매도",
            "순이익이 1년 전보다 줄었고, 영업으로 벌어들이는 현금도 줄었는데, 주가는 평소(4년 평균)보다 25% 이상 비싸게 거래되는 종목",
            "ni_1y↓  AND  cfo_1y↓  AND  P/NI 고평가(per_ni_20d/per_ni_4y &gt; 1.25)",
            v["sell"], [3, 6, 9, 12], v["events_n"],
        ),
    )
    vb = v["baseline_12m"]
    html = html.replace("__V_BASE_RAW__", f"mean {_fmt_pct(vb['raw_mean'])} / median {_fmt_pct(vb['raw_median'])}")
    html = html.replace("__V_BASE_ALPHA__", f"mean {_fmt_pct(vb['alpha_mean'])} / median {_fmt_pct(vb['alpha_median'])}")

    weight = bench["mega_cap_weight_pct"]
    html = html.replace("__MEGA_WEIGHT__", f"{weight:.1f}" if weight is not None else "—")
    rets = bench["returns"]
    parts = []
    for name in MEGA_CAP_NAMES:
        r = rets.get(name)
        if r:
            parts.append(f"{name} {r['start_date']}~{r['end_date']} {_fmt_pct(r['ret_12m_pct'])}")
        else:
            parts.append(f"{name} 데이터 없음")
    html = html.replace("__MEGA_RET_1__", parts[0] if len(parts) > 0 else "—")
    html = html.replace("__MEGA_RET_2__", parts[1] if len(parts) > 1 else "—")

    return html


def main() -> int:
    if not (PANEL_CSV.is_file() and PIT_DB.is_file() and PRICES_DB.is_file()):
        print("mcap200_factor_panel.csv / pit_buckets.db / prices.db 없음")
        return 1

    g = compute_growth_signals()
    v = compute_value_signals()
    bench = compute_benchmark_note()
    stocks = compute_stock_rows()

    html = generate_html(g, v, bench, stocks)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_HTML} ({len(html):,} bytes, {len(stocks)}종목)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
