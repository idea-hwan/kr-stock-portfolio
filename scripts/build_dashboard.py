"""
대형 성장주·밸류주 확정 신호 4개(매수/매도 × 성장/밸류) 판단로직 대시보드.

us-stock-portfolio의 build_dashboard.py와 같은 원칙 — 순수 Python이 정적 HTML 1개를
만든다. Jinja2·React·차트 라이브러리·외부 CDN 전부 없음(인라인 CSS/JS만, 오프라인 동작).
차이점: 미국 쪽 "판단로직" 패널의 백테스트 숫자는 손으로 박아넣은 값이라 방법론이 바뀌면
사람이 다시 계산해야 하고 조용히 stale해진다(2026-07-23 발견) — 여기서는 이 스크립트가
매번 signal_common.py로 raw/alpha를 직접 재계산해서 채운다. 종목별 현재 매수/매도 후보
테이블은 이후 단계(매수 추천 리포트)로 미룬다 — 이 v1은 신호 방법론·백테스트 카드만.

출력: docs/index.html
실행: .venv/bin/python scripts/build_dashboard.py
"""

from __future__ import annotations

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
OUT_HTML = _ROOT / "docs" / "index.html"

MEGA_CAP_NAMES = ("삼성전자", "SK하이닉스")


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

    import sqlite3

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
<title>대형 성장주·밸류주 판단로직</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {
  --bg: #0d1117; --panel: #161b22; --border: #30363d;
  --text: #e6edf3; --sub: #8b949e; --pos: #3fb950; --neg: #f85149; --accent: #58a6ff;
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font-family: -apple-system, "Pretendard", "Malgun Gothic", sans-serif; }
.wrap { max-width: 980px; margin: 0 auto; padding: 32px 20px 80px; }
h1 { font-size: 22px; margin-bottom: 4px; }
.meta { color: var(--sub); font-size: 13px; margin-bottom: 28px; }
h2 { font-size: 16px; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-top: 40px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
@media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px 18px; }
.card h3 { margin: 0 0 6px; font-size: 14px; }
.plain { font-size: 13px; color: var(--text); margin: 0 0 8px; line-height: 1.6; }
.formula { font-size: 11px; color: var(--sub); font-family: monospace; margin: 0 0 10px; line-height:1.5; background: rgba(255,255,255,0.03); padding: 6px 8px; border-radius: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { padding: 5px 6px; text-align: right; border-bottom: 1px solid var(--border); }
th:first-child, td:first-child { text-align: left; }
.num { font-variant-numeric: tabular-nums; }
.sub { color: var(--sub); font-size: 10px; }
.note { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px 18px; font-size: 13px; line-height: 1.7; margin-top: 16px; }
.note b { color: var(--accent); }
.baseline { color: var(--sub); font-size: 12px; margin-top: 10px; }
footer { color: var(--sub); font-size: 11px; margin-top: 48px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>대형 성장주·밸류주 판단로직</h1>
  <p class="meta">생성 시각: __GENERATED_AT__ · 데이터: mcap200_factor_panel.csv, pit_buckets.db, prices.db (매 실행마다 재계산 — 캐시된 숫자 아님)</p>
  <p class="meta">아래 표의 수익률은 전부 <b>미래(forward) 수익률</b>이다 — 이 조건을 만족한 시점에 실제로
  샀다고 가정하고, 그 이후 3/6/9/12개월 동안 얼마를 벌었는지를 계산한 것이다(과거 추세가 아니다).</p>

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

  <footer>재현: .venv/bin/python scripts/build_dashboard.py · 신호 정의: docs/large_growth_selection_strategy.md, docs/large_value_selection_strategy.md</footer>
</div>
</body>
</html>
"""


def generate_html(g: dict, v: dict, bench: dict) -> str:
    html = HTML_TEMPLATE

    from datetime import datetime, timezone

    html = html.replace("__GENERATED_AT__", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

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

    html = generate_html(g, v, bench)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_HTML} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
