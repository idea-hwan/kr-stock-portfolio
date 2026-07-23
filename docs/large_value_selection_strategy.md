# 대형 밸류주 매수/홀딩/매도 선정 전략

> 매수 run_id=2(2026-07-23) · 매도 run_id=3(2026-07-23) / PIT 교정 + 유틸리티·지주회사
> 제외 유니버스(value_pit16, 120종목·1782이벤트), KOSPI200 대비 alpha 기준.
> **매수·매도 신호 모두 확정.**
> `large_growth_selection_strategy.md`와 유니버스 구성 원칙은 동일 — 버킷 조건(연속
> 흑자 지표)만 다르다: growth_pit16은 영업이익(`op_ps`) 16분기 연속 흑자, value_pit16은
> **순이익(`ni_parent_ps`) 16분기 연속 흑자**.

---

## 1. 핵심 원칙 (확정)

```
싸다고(per_ratio<0.5) 무조건 사지 않는다 — 영업이익이 꺾이고 있으면 가치함정이다.
"싸다" + "영업이익이 1년 전보다 늘었다"를 동시에 만족하는 종목만 산다.
```

growth와 달리 밸류 버킷은 "성장 가속"을 요구하지 않는다 — 다만 per_ratio(저평가) 단독으로는
어떤 구간(<0.5, 0.5~1.0, …, 2.0+)도 alpha mean·median이 둘 다 플러스가 아니었다(§4).
"얼마나 싼가"만으로는 신호가 안 서고, 이익이 최소한 역성장은 아니어야 한다는 품질 조건이
붙어야 신호가 산다.

---

## 2. 유니버스

`value_pit16` — `data/analytics/mcap200_factor_panel.csv` ⋈
`data/analytics/pit_buckets.db::pit_buckets16`

| 조건 | 내용 |
|------|------|
| 시총 | `mcap_top_200.csv` 편입 (대형주) |
| 이익 안정성 | 그 분기 시점까지 최근 16분기 연속 `ni_parent_ps > 0` (롤링 재판정, 생존편향 없음) |
| 업종 제외 | 유틸리티(한국전력 등)·지주회사(SK·LG·GS 등) 제외 (growth와 동일 필터) |
| 종목·이벤트 수 | 120종목, 1,782개 (종목·분기) 이벤트, term 2020Q3~2026Q1 |

---

## 3. 확정 매수 신호

```
Signal A (저평가) = per_ratio = per_op_20d / per_op_4y   (영업이익 기준, op→ni→rev 폴백)
Signal B (품질)   = op_geom_1y_mcum > 0                  (영업이익 1년 성장 플러스)

매수 신호 = per_ratio < 0.5   AND   op_1y > 0
```

---

## 4. 백테스트 근거 (value_pit16, n=1782, KOSPI200 대비 alpha, 12m)

| | n | alpha mean/median |
|---|---|---|
| 전체(baseline) | 1782 | -5.8% / -7.9% |
| ratio<0.5 (단독) | 184 | +4.5% / -1.2% |
| ratio[0.5,1.0) (단독) | 894 | -9.2% / -8.8% |
| ratio[1.0,1.5) (단독) | 426 | -2.7% / -5.5% |
| ratio[1.5,2.0) (단독) | 146 | -13.5% / -16.2% |
| ratio≥2.0 (단독) | 132 | +1.0% / -18.5% |
| **확정 신호: ratio<0.5 AND op_1y>0** | **153** | **+10.5% / +4.2%** |

per_ratio 구간은 **어느 것도** mean·median이 둘 다 플러스가 아니다 — 가장 근접한 ratio<0.5도
median -1.2%로 마이너스. `op_1y>0`(영업이익 1년 성장) 품질 필터를 얹은 뒤에야 확정 신호가
mean·median 둘 다 플러스로 전환됐다. 41종목·153이벤트로 표본도 충분히 크고, 15m/18m까지도
median이 거의 그대로 유지된다(12m +4.2% → 15m +4.1% → 18m +4.0%) — growth 확정 신호가
15m부터 median이 마이너스로 돌아선 것과 달리 **보유기간에 덜 민감한 안정적 신호**다.

### 4.1 참고 — 검토했으나 채택 안 함

| 조합 | n | alpha 12m mean/median | 비고 |
|---|---|---|---|
| ratio<0.5 + cfo_1y>0 | 109 | +10.5% / +4.2% | 12m은 확정 신호와 동일하지만 18m median이 -1.8%로 반전 — op_1y>0보다 불안정 |
| ratio<0.5 + cfo_1y>0 + fcf_1y<=0 | 27 | +31.0% / +20.5% | 가장 강하지만 표본 너무 작음(2.7% of universe) — 안전 마진으로 미채택 |
| ratio<0.5 + rev_1y>0 | 159 | +3.6% / +0.9% | op_1y>0보다 약함 — 매출성장보다 영업이익성장이 더 강한 필터 |
| ratio<0.5 (단독) | 184 | +4.5% / -1.2% | 옛 run_id=1 신호(PIT 교정 전) — median 마이너스라 폐기 |

---

## 5. 매수 기준

```
매수: per_ratio < 0.5  AND  op_geom_1y_mcum > 0
      → alpha mean +10.5%, median +4.2%(n=153, 12m 기준)

해당 없음 → 매수 없음. per_ratio<0.5만 보고 사지 않는다 — 영업이익이
1년 전보다 줄었다면(가치함정) 아무리 싸도 매수 안 함.
```

---

## 6. 매도 확정 신호 (run_id=3 / as_of=2026-07-23)

`large_growth_selection_strategy.md` §7과 동일한 3축 그리드서치(성장꺾임·고평가·투자압박,
3/6/9개월 alpha)를 value_pit16에 적용했다. **growth와 완전히 동일한 3팩터 조합이 독립적으로
1위를 차지했다** — 성장주·밸류주 공통의 "위험 신호"로 보인다.

```
매도: ni_1y↓(순이익 1년 역성장) AND cfo_1y↓(영업현금흐름 1년 역성장)
      AND P/NI 고평가(per_ni_20d / per_ni_4y > 1.25)

→ alpha(KOSPI200) mean/median: 3m -12.7%/-12.4%, 6m -16.6%/-13.1%,
  9m -28.4%/-18.8%, 12m -40.5%/-22.9%  (n=127, 65종목, 2020Q3~2026Q1)

보유 기간이 늘어날수록 악화(3m→12m mean -12.7%→-40.5%) — growth 매도 신호(large_growth_
selection_strategy.md §7, n=148, -11.7%~-35.2%)와 강도·패턴 모두 유사하다.
```

### 6.1 홀딩

```
§6 매도 조건 미충족 → 홀딩
```

---

## 7. 미결 사항

```
- 매수·매도 신호 모두 out-of-sample 검증 아직 안 함(growth와 동일한 미결 사항).
- P/FCF는 fcf_ps(roll4 TTM, FY우선폴백 없음) 기반 간이 버전 — 결측이 P/OP·P/NI보다 많다.
- §4.1의 "ratio<0.5 + cfo_1y>0 + fcf_1y<=0"(n=27, alpha +31%)은 표본이 작아 미채택했지만
  이벤트가 쌓이면 재검토 가치 있음.
```

---

*매수 run_id=2 / as_of=2026-07-23 / 확정 신호: per_ratio<0.5 AND op_1y>0, value_pit16, alpha(KOSPI200) 기준*
*매도 run_id=3 / as_of=2026-07-23 / 확정 신호: ni_1y↓ + cfo_1y↓ + P/NI 고평가(>1.25), value_pit16, alpha(KOSPI200) 기준*
*재현: `.venv/bin/python scripts/simulate/verify_value_signal.py`, `.venv/bin/python scripts/simulate/value_factor_grid.py` (매수)*
*`.venv/bin/python scripts/simulate/value_sell_factor_grid.py` (매도)*
