"""
`ttm_valuation.db` 시계열에서 **분기성장률(%)** (`cum`) 과 **다기간 누적 %** (`1y_%` … `8y_%`, DB 컬럼 `*_geom_*y_mcum`)를 만든다.

데이터 소스: `scripts.analysis.ttm_valuation_df.load_ttm_valuation_df`

대상 지표(행은 ttm_end_term 기준 TTM 스냅샷):
  - 매출/영업이익/지배순이익: DB의 rev_ps, op_ps, ni_parent_ps(롤4 원천)에 대해
    `scripts.analysis.series_per` 의 액면 보정과 **동일한 계수**(최신 공시일 기준 역방향
    fv_prev/fv_i 체인)를 곱한 뒤 성장률을 계산한다. PER 분모(Rev_adj 등)와 같은 축.
    ※ PER 쪽은 4Q에 FY 주당을 쓸 수 있으나, 여기서는 성장 일관성을 위해 **롤4 주당만** 보정한다.
  - CFO·Capex·FCF: ttm_cfo_krw, ttm_capex_krw, ttm_fcf_krw (원 단위 TTM, 액면 보정 없음)

규칙(요청 스펙):
  - **음수·0**이 끼면 연속 QoQ 경로는 막힘(내부 계산). 적자 구간은 **보류**.
  - **직전 적자 → 당기 흑자**면 QoQ는 NaN, **수정 누적(cum)** 만 마지막 양수 앵커~당기로 한 번에 반영.
  - 직전 분기 대비 0이 끼는 경우: prev==0 이고 curr>0 인 «첫 회복 분기»는 성장률 미표시(NaN).
  - 연속 양수 QoQ: prev>0, curr>0, 직전전 분기 값이 0이 아님(0 → 양 → 양 패턴의 두 번째 양은 QoQ 대신 구간 성장).
  - 그 외 구간 성장: 앵커 j에서 curr 까지 (j,i] 구간에 음수 있으면 NaN. span_q = i - j.
  - **내부 QoQ%**: 연속 양수일 때만 (curr/prev-1)×100 — **출력 컬럼에는 포함하지 않음**.
  - **구간 cum_geom_pct**: 앵커~당기 비율 R, span=k → **분기당 기하평균 %** (R^(1/k)-1)×100.
    span=1 이면 QoQ와 동일.
  - **geom_{1y,2y,4y,8y}_mcum** (화면 `1y_%`…): 최근 k분기(k=4,8,16,32) cum으로 P=∏(1+g_t),
    None→0, 전부 None 이면 None, %=(P^(1/k)-1)×100.
  - **{1y,2y,4y,8y}_q_empty**: 해당 k분기 창에서 [0,n) 이고 cum 이 None 인 분기 수.
  - **{1y,2y,4y,8y}_q_minus**: 같은 창에서 TTM 원시값이 **음수(<0)** 인 분기 수.

split 출력: 분기·분기성장률(%)·span·1y_%~8y_%·q_empty·q_minus (QoQ·단순끝점 ∘ 미표시).

예:
  .venv/bin/python scripts/screening/ttm_metric_growth.py --company 삼성전자
  .venv/bin/python scripts/screening/ttm_metric_growth.py --company 삼성전자 --view wide
  문서: docs/ttm_metric_growth.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.analysis.series_per import filing_anchor_date
from scripts.analysis.ttm_valuation_df import load_ttm_valuation_df

DEFAULT_DB = _ROOT / "data" / "analytics" / "ttm_valuation.db"

# (lag 분기 수, 표기 라벨)
_HORIZONS: tuple[tuple[int, str], ...] = (
    (4, "1y"),
    (8, "2y"),
    (16, "4y"),
    (32, "8y"),
)

# (column, prefix, PL액면보정)
_METRICS: tuple[tuple[str, str, bool], ...] = (
    ("rev_ps", "rev", True),
    ("op_ps", "op", True),
    ("ni_parent_ps", "ni", True),
    ("ttm_cfo_krw", "cfo", False),
    ("ttm_capex_krw", "capex", False),
    ("ttm_fcf_krw", "fcf", False),
)


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (ValueError, TypeError):
        pass
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if np.isnan(x) or np.isinf(x):
        return None
    return x


def _series_floats(col: pd.Series) -> list[float | None]:
    return [_to_float(x) for x in col.tolist()]


def _neg_in_interval(values: list[float | None], lo: int, hi: int) -> bool:
    """(lo, hi] inclusive hi, exclusive lo — indices into values."""
    for m in range(lo + 1, hi + 1):
        t = values[m]
        if t is not None and t < 0:
            return True
    return False


def _max_positive_index_before(values: list[float | None], before: int) -> int | None:
    best: int | None = None
    for k in range(before - 1, -1, -1):
        t = values[k]
        if t is not None and t > 0:
            return k
    return best


def _geom_mean_pct_per_step(ratio: float, n_steps: int) -> float:
    """
    k구간 비율 R에 대한 **분기당(스텝당) 기하평균 성장률 %**: (R^(1/k) - 1)×100.
    수정 누적(cum) 구간비 R, span=k 일 때 분기당 % (R^(1/k)-1)×100. k=1 이면 (R-1)×100.
    """
    if n_steps < 1:
        raise ValueError("n_steps must be >= 1")
    return float((ratio ** (1.0 / float(n_steps)) - 1.0) * 100.0)


def _horizon_modified_cumulative_pct(
    cum: list[float | None], i: int, lag_q: int
) -> float | None:
    """
    최근 lag_q 분기(인덱스 i−lag_q+1 … i)에 대해 P=∏(1+g_t), g_t=cum/100, None→0.
    [0,n)에 속한 인덱스만 모두 cum None 이면 None. P≤0 이면 None.
    반환 % = (P^(1/lag_q) - 1)×100.
    """
    if lag_q < 1:
        raise ValueError("lag_q must be >= 1")
    n = len(cum)
    lo = i - lag_q + 1
    in_bounds = [j for j in range(lo, i + 1) if 0 <= j < n]
    if in_bounds and all(cum[j] is None for j in in_bounds):
        return None
    prod = 1.0
    for j in range(lo, i + 1):
        if j < 0 or j >= n or cum[j] is None:
            g = 0.0
        else:
            g = float(cum[j]) / 100.0
        prod *= 1.0 + g
    if prod <= 0:
        return None
    return float((prod ** (1.0 / float(lag_q)) - 1.0) * 100.0)


def _window_cum_blank_count(
    cum: list[float | None], i: int, n: int, lag_q: int
) -> int:
    """인덱스 i−lag_q+1 … i 중 [0,n) 이고 cum[j] is None 인 분기 수."""
    lo = i - lag_q + 1
    c = 0
    for j in range(lo, i + 1):
        if 0 <= j < n and cum[j] is None:
            c += 1
    return c


def _window_ttm_neg_count(
    vals: list[float | None], i: int, n: int, lag_q: int
) -> int:
    """같은 창에서 TTM 값이 음수(<0)인 분기 수(해당 인덱스만 세며 None 은 제외)."""
    lo = i - lag_q + 1
    c = 0
    for j in range(lo, i + 1):
        if 0 <= j < n:
            v = vals[j]
            if v is not None and v < 0:
                c += 1
    return c


def _adjust_roll4_pl_ps_for_growth(df: pd.DataFrame) -> tuple[
    list[float | None],
    list[float | None],
    list[float | None],
]:
    """
    series_per._adjusted_valuation_table_from_series 와 동일한 factor 체인으로
    롤4 주당(rev/op/ni)을 최신 액면 스케일로 맞춘다.
    """
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        te = str(r.get("ttm_end_term", "") or "").strip()
        if not te:
            continue
        rows.append(
            {
                "term": te,
                "filing_date": filing_anchor_date(te),
                "FaceValue": _to_float(r.get("face_value_end")),
                "Rev_raw": _to_float(r.get("rev_ps")),
                "Op_raw": _to_float(r.get("op_ps")),
                "Ni_raw": _to_float(r.get("ni_parent_ps")),
            }
        )
    if not rows:
        n = len(df)
        return [None] * n, [None] * n, [None] * n

    adf = pd.DataFrame(rows)
    adf["FaceValue_num"] = pd.to_numeric(adf["FaceValue"], errors="coerce")
    adf["FaceValue_ffill"] = adf["FaceValue_num"].ffill().bfill()
    if adf["FaceValue_ffill"].isna().all():
        adf["FaceValue_ffill"] = 1.0

    ndf = adf.sort_values("filing_date", ascending=False).reset_index(drop=True)
    factors: list[float] = []
    rev_adj: list[float | None] = []
    op_adj: list[float | None] = []
    ni_adj: list[float | None] = []

    for i in range(len(ndf)):
        fv_i = float(ndf.loc[i, "FaceValue_ffill"])
        if i == 0:
            fac = 1.0
        else:
            fv_prev = float(ndf.loc[i - 1, "FaceValue_ffill"])
            if fv_i == fv_prev:
                fac = factors[i - 1]
            else:
                fac = fv_prev / fv_i if fv_i != 0 else 1.0
        factors.append(fac)
        for col, lst in (
            ("Rev_raw", rev_adj),
            ("Op_raw", op_adj),
            ("Ni_raw", ni_adj),
        ):
            er = ndf.loc[i, col]
            if er is None or (isinstance(er, float) and np.isnan(er)):
                lst.append(None)
            else:
                lst.append(float(er) * fac)

    ndf["rev_adj"] = rev_adj
    ndf["op_adj"] = op_adj
    ndf["ni_adj"] = ni_adj
    merged = ndf.sort_values("filing_date", ascending=True)
    term_map: dict[str, tuple[float | None, float | None, float | None]] = {}
    for _, r in merged.iterrows():
        te = str(r["term"])
        term_map[te] = (
            None if r["rev_adj"] is None or pd.isna(r["rev_adj"]) else float(r["rev_adj"]),
            None if r["op_adj"] is None or pd.isna(r["op_adj"]) else float(r["op_adj"]),
            None if r["ni_adj"] is None or pd.isna(r["ni_adj"]) else float(r["ni_adj"]),
        )

    rev_out: list[float | None] = []
    op_out: list[float | None] = []
    ni_out: list[float | None] = []
    for _, r in df.iterrows():
        te = str(r.get("ttm_end_term", "") or "").strip()
        a, b, c = term_map.get(te, (None, None, None))
        rev_out.append(a)
        op_out.append(b)
        ni_out.append(c)
    return rev_out, op_out, ni_out


def _growth_for_metric(
    values: list[float | None],
) -> tuple[list[float | None], list[float | None], list[int | None]]:
    n = len(values)
    qoq: list[float | None] = [None] * n
    cum: list[float | None] = [None] * n
    span: list[int | None] = [None] * n

    for i in range(n):
        if i == 0:
            continue

        curr, prev = values[i], values[i - 1]
        if curr is None or prev is None:
            continue

        prev_prev = values[i - 2] if i >= 2 else None
        zero_gap = i >= 2 and prev_prev is not None and prev_prev == 0

        # --- QoQ: 연속 양수만 (음수 구간은 전부 패스) ---
        qoq_pos = prev > 0 and curr > 0 and not zero_gap
        if qoq_pos:
            qoq[i] = float((curr / prev - 1.0) * 100.0)

        # --- 구간 누적·span: 당기 양수(0→흑자 첫 분기 제외) ---
        if curr <= 0:
            continue

        if prev == 0 and curr > 0:
            continue

        if qoq_pos:
            cum[i] = _geom_mean_pct_per_step(curr / prev, 1)
            span[i] = 1
            continue

        # 직전 적자 → 당기 흑자: 마지막 양수 앵커~당기, 중간 적자 허용. cum=분기당 기하평균%.
        if prev < 0:
            j = _max_positive_index_before(values, i)
            if j is not None:
                anchor = values[j]
                if anchor is not None and anchor > 0:
                    span_q = i - j
                    if span_q >= 1:
                        ratio = curr / anchor
                        if ratio > 0:
                            cum[i] = _geom_mean_pct_per_step(ratio, span_q)
                            span[i] = span_q
            continue

        # 앵커 j — 구간 분기당 기하평균 %
        if (
            prev > 0
            and curr > 0
            and i >= 2
            and prev_prev is not None
            and prev_prev == 0
        ):
            j = _max_positive_index_before(values, i - 1)
        else:
            j = _max_positive_index_before(values, i)

        if j is None:
            continue
        anchor = values[j]
        if anchor is None or anchor <= 0:
            continue
        if _neg_in_interval(values, j, i):
            continue

        span_q = i - j
        ratio = curr / anchor
        if ratio <= 0:
            continue
        cum[i] = _geom_mean_pct_per_step(ratio, span_q)
        span[i] = span_q

    return qoq, cum, span


def build_ttm_metric_growth_df(
    company: str,
    *,
    db_path: Path | None = None,
    anchor_term: str | None = None,
    computed_at: str | None = None,
) -> pd.DataFrame:
    raw = load_ttm_valuation_df(
        company,
        db_path=db_path,
        anchor_term=anchor_term,
        computed_at=computed_at,
    )
    if raw.empty:
        return pd.DataFrame()

    df = raw.sort_values("ttm_end_term", kind="mergesort").reset_index(drop=True)
    out = df[["ttm_end_term"]].copy()

    rev_adj_l: list[float | None] | None = None
    op_adj_l: list[float | None] | None = None
    ni_adj_l: list[float | None] | None = None
    if all(c in df.columns for c in ("rev_ps", "op_ps", "ni_parent_ps", "face_value_end")):
        rev_adj_l, op_adj_l, ni_adj_l = _adjust_roll4_pl_ps_for_growth(df)

    pl_vals: dict[str, list[float | None] | None] = {
        "rev_ps": rev_adj_l,
        "op_ps": op_adj_l,
        "ni_parent_ps": ni_adj_l,
    }
    for col, prefix, pl_adj in _METRICS:
        if col not in df.columns:
            continue
        av = pl_vals.get(col) if pl_adj else None
        vals = av if av is not None else _series_floats(df[col])
        _qoq, cum_geom_pct, sp = _growth_for_metric(vals)
        out[f"{prefix}_cum_geom_pct"] = cum_geom_pct
        out[f"{prefix}_span_q"] = pd.array(
            [pd.NA if s is None else int(s) for s in sp],
            dtype="Int64",
        )
        nn = len(cum_geom_pct)
        for lag_q, ylab in _HORIZONS:
            out[f"{prefix}_geom_{ylab}_mcum"] = [
                _horizon_modified_cumulative_pct(cum_geom_pct, idx, lag_q)
                for idx in range(nn)
            ]
            out[f"{prefix}_{ylab}_q_empty"] = pd.array(
                [
                    _window_cum_blank_count(cum_geom_pct, idx, nn, lag_q)
                    for idx in range(nn)
                ],
                dtype="Int64",
            )
            out[f"{prefix}_{ylab}_q_minus"] = pd.array(
                [
                    _window_ttm_neg_count(vals, idx, nn, lag_q)
                    for idx in range(nn)
                ],
                dtype="Int64",
            )

    return out


def _split_cols_for_prefix(prefix: str) -> tuple[list[str], list[str]]:
    cols = [
        "ttm_end_term",
        f"{prefix}_cum_geom_pct",
        f"{prefix}_span_q",
    ]
    heads = ["분기", "분기성장률(%)", "span"]
    for _, ylab in _HORIZONS:
        cols.extend(
            [
                f"{prefix}_geom_{ylab}_mcum",
                f"{prefix}_{ylab}_q_empty",
                f"{prefix}_{ylab}_q_minus",
            ]
        )
        heads.extend([f"{ylab}_%", f"{ylab}_q_empty", f"{ylab}_q_minus"])
    return cols, heads


def _display_groups() -> list[tuple[str, list[str], list[str]]]:
    """콘솔 split: 분기·분기성장률·span·1·2·4·8년 각 %·q_empty·q_minus."""
    return [
        ("[1] 매출/주", *_split_cols_for_prefix("rev")),
        ("[2] 영업/주", *_split_cols_for_prefix("op")),
        ("[3] 지배순/주", *_split_cols_for_prefix("ni")),
        ("[4] CFO", *_split_cols_for_prefix("cfo")),
        ("[5] Capex", *_split_cols_for_prefix("capex")),
        ("[6] FCF", *_split_cols_for_prefix("fcf")),
    ]


def _fmt_growth_display(col: str, v: Any) -> str:
    if col == "ttm_end_term":
        if v is None:
            return "—"
        try:
            if pd.isna(v):
                return "—"
        except (ValueError, TypeError):
            pass
        return str(v).strip()
    if v is None:
        return "—"
    try:
        if pd.isna(v):
            return "—"
    except (ValueError, TypeError):
        pass
    if (
        col.endswith("_span_q")
        or col.endswith("_q_empty")
        or col.endswith("_q_minus")
    ):
        try:
            if pd.isna(v):
                return "—"
        except (TypeError, ValueError):
            pass
        try:
            return str(int(v))
        except (TypeError, ValueError):
            return "—"
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _growth_display_block(g: pd.DataFrame, src_cols: list[str], head: list[str]) -> pd.DataFrame:
    sub = g.loc[:, [c for c in src_cols if c in g.columns]].copy()
    disp = pd.DataFrame()
    for i, c in enumerate(sub.columns):
        disp[head[i] if i < len(head) else c] = sub[c].map(lambda x, col=c: _fmt_growth_display(col, x))
    return disp


def print_growth_split(g: pd.DataFrame, company: str) -> None:
    print(
        f"company={company}  rows={len(g)}  "
        "(split=분기·분기성장률·span·1y~8y_%·q_empty·q_minus; wide=전열)"
    )
    print()
    for title, src_cols, head in _display_groups():
        use_cols = [c for c in src_cols if c in g.columns]
        if len(use_cols) <= 1:
            continue
        disp = _growth_display_block(g, use_cols, head[: len(use_cols)])
        print(title)
        with pd.option_context("display.width", 500, "display.max_colwidth", 12):
            print(disp.to_string(index=False))
        print()


def print_growth_wide(g: pd.DataFrame, company: str) -> None:
    cols = list(g.columns)
    disp = pd.DataFrame({c: g[c].map(lambda x, col=c: _fmt_growth_display(col, x)) for c in cols})
    print(f"company={company}  rows={len(g)}  view=wide")
    with pd.option_context("display.max_columns", None, "display.width", 400):
        print(disp.to_string(index=False))


def main() -> int:
    p = argparse.ArgumentParser(
        description="ttm_valuation.db → 분기성장률·1y~8y 누적 % DataFrame",
    )
    p.add_argument("--company", default="삼성전자", help="종목명 (stock_listing Name)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="ttm_valuation.db 경로")
    p.add_argument("--anchor-term", default=None, help="예: 2025Q4")
    p.add_argument("--computed-at", default=None, help="특정 배치만")
    p.add_argument(
        "--view",
        choices=("split", "wide"),
        default="split",
        help="split=지표별 좁은 표(기본), wide=전열 한 줄",
    )
    args = p.parse_args()

    try:
        g = build_ttm_metric_growth_df(
            args.company,
            db_path=args.db,
            anchor_term=args.anchor_term,
            computed_at=args.computed_at,
        )
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    if g.empty:
        print(f"'{args.company}' 성장률 테이블 없음 (원본 비어 있음).")
        return 2

    pd.set_option("display.unicode.east_asian_width", True)
    if args.view == "wide":
        print_growth_wide(g, args.company)
    else:
        print_growth_split(g, args.company)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
