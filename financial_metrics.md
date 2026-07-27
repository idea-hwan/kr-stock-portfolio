# 재무 지표 정의

`ttm_valuation.db`·`ttm_metric_growth.db`(→ 대형 성장/밸류 버킷·매수신호 문서)가
실제로 계산하는 값을 해석할 때 참고하는 정의만 남긴다. (2026-07-27 정리 —
이 프로젝트에서 계산하지 않는 레버리지·유동성·효율성·섹터별·GPS 복합 지표 등
일반 재무 교과서 항목은 제거했다.)

---

## 1. 수익성 지표 (Profitability)

| 지표 | 계산식 | 설명 |
|------|--------|------|
| **EPS** | Net Income / Diluted Shares | 주당순이익 |
| **EPS Diluted** | Net Income / (기본주식 + 희석주식) | 희석 주당순이익 |
| **Gross Profit** | Revenue - COGS | 매출총이익 |
| **Gross Margin** | Gross Profit / Revenue | 매출총이익률 |
| **Operating Income (OI)** | Gross Profit - OpEx | 영업이익 |
| **OI Margin** | Operating Income / Revenue | 영업이익률 |
| **EBITDA** | OI + D&A | 이자·세금·감가상각 전 이익 |
| **EBITDAR** | EBITDA + Rent/Lease | 임차료 제외 EBITDA |
| **Net Income** | OI - Interest - Tax | 순이익 |
| **Net Margin** | Net Income / Revenue | 순이익률 |
| **ROE** | Net Income / Equity | 자기자본이익률 |
| **ROA** | Net Income / Total Assets | 총자산이익률 |
| **ROIC** | NOPAT / Invested Capital | 투하자본이익률 |
| **ROCE** | EBIT / Capital Employed | 사용자본이익률 |

---

## 2. 현금흐름 지표 (Cash Flow)

| 지표 | 계산식 | 설명 |
|------|--------|------|
| **Operating Cash Flow (OCF)** | Net Income + D&A ± ΔNWC | 영업현금흐름 |
| **Capex** | PP&E 취득 지출 | 자본적 지출 |
| **Capex / Sales** | Capex / Revenue | 매출 대비 자본지출 비율 |
| **FCFF** | EBIT×(1-t) + D&A - Capex - ΔNWC | 기업 잉여현금흐름 |
| **FCFE** | FCFF - Interest×(1-t) + Net Borrowing | 주주 잉여현금흐름 |
| **FCF Margin** | FCF / Revenue | FCF 이익률 |
| **Cash Conversion Ratio (CCR)** | OCF / Net Income | 이익의 현금화 비율 |

---

## 3. 밸류에이션 지표 (Valuation)

| 지표 | 계산식 | 설명 |
|------|--------|------|
| **P/E** (`per_ni_*`) | 주가 / 주당순이익 | 순이익 기준 PER |
| **P/OP** (`per_op_*`) | 주가 / 주당영업이익 | 영업이익 기준 PER |
| **P/S** (`per_rev_*`) | 주가 / 주당매출 | 매출 기준 PER |
| **P/FCF** (`per_fcf_*`) | 주가 / 주당FCF | FCF 기준 PER |
| **Dividend Yield** | DPS / 주가 | 배당수익률 (`dividend_valuation_series.py`) |
| **Payout Ratio** | DPS / EPS | 배당성향 |

---

## 4. 성장성 지표 (Growth)

| 지표 | 계산식 | 설명 |
|------|--------|------|
| **Revenue Growth (YoY)** | (매출₁ - 매출₀) / 매출₀ | 매출 증가율 |
| **Revenue CAGR** | (매출ₙ / 매출₀)^(1/n) - 1 | 연평균 매출 성장률 |
| **EBITDA Growth** | ΔEBITDA / EBITDA₀ | EBITDA 증가율 |
| **EPS Growth** | ΔEPS / EPS₀ | 주당순이익 증가율 |
| **Organic Growth** | M&A 제외 내생적 성장률 | 순수 영업 성장 |

---
