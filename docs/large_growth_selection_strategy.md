# 대형 성장주 매수/홀딩/매도 선정 전략

> run_id=5 / as_of=2026-07-22 / PIT 교정 + 유틸리티·지주회사 제외 유니버스
> (growth_pit16, 141종목·2468이벤트), KOSPI200 대비 alpha 기준. **신호 확정.**
> 근거: [large_growth_pit_signal_verify.md](methodology/large_growth_pit_signal_verify.md) §5.

---

## 1. 핵심 원칙 (확정)

```
적당히 저평가되어 있고(per_ratio 0.5~1.0), 영업이익이 적당히 가속하는
(acceleration 2~5배) 종목을 산다.

너무 싼 것(<0.5)도, 너무 안 싼 것(≥1.0)도 아니다.
너무 안 크는 것(<2배)도, 너무 급하게 크는 것(≥5배)도 아니다.
```

극단(가장 싸다, 가장 빨리 큰다)이 아니라 **중간 구간**이 이긴다는 게 핵심이다. 가장 싼
구간(<0.5)과 가장 급가속하는 구간(≥5배)은 둘 다 alpha가 마이너스였다 — 전자는 유틸리티·
지주회사처럼 구조적으로 저PER인 종목이 섞여 있던 착시였고, 후자는 기저효과(적자 근처
저점 대비 회복)로 인위적으로 부풀려진 가속인 경우가 많았다.

---

## 2. 유니버스

`growth_pit16` — `data/analytics/mcap200_factor_panel.csv` ⋈
`data/analytics/pit_buckets.db::pit_buckets16`

| 조건 | 내용 |
|------|------|
| 시총 | `mcap_top_200.csv` 편입 (대형주) |
| 이익 안정성 | 그 분기 시점까지 최근 16분기 연속 `op_ps > 0` (롤링 재판정, 생존편향 없음) |
| 업종 제외 | 유틸리티(한국전력 등)·지주회사(SK·LG·GS 등) 제외 |
| 종목·이벤트 수 | 141종목, 2,468개 (종목·분기) 이벤트, term 2020Q3~2026Q1 |

---

## 3. 확정 신호

```
Signal A (저평가) = per_ratio = per_op_20d / per_op_4y   (영업이익 기준, op→ni→rev 폴백)
Signal B (가속)   = acceleration = op_geom_1y_mcum / op_geom_4y_mcum

매수 신호 = 0.5 ≤ per_ratio < 1.0   AND   2 ≤ acceleration < 5
```

---

## 4. 백테스트 근거 (growth_pit16, n=2468, KOSPI200 대비 alpha)

| | n | raw mean/median | **alpha mean/median** |
|---|---|---|---|
| 전체(baseline) | 2468 | +22.4% / -0.2% | -8.5% / -10.5% |
| **확정 신호: ratio[0.5,1) + accel[2,5)** | **162** | **+26.9% / +5.2%** | **+9.7% / +2.1%** |
| (참고) ratio<0.5 단독 | 345 | +15.7% / +0.5% | -10.3% / -9.9% |
| (참고) accel≥2 단독 (상한 없음) | 541 | +20.7% / 0.0% | -0.3% / -3.7% |

이 유니버스 전체가 시장(KOSPI200) 대비 alpha -8.5%로 계속 졌던 와중에, 확정 신호만
**mean·median 둘 다 플러스**(+9.7%p / +2.1%p, baseline 대비 +18.2%p 우위)다. n=162로
이 전략에서 다룬 조합 중 가장 표본이 크면서 동시에 median까지 살아있는 유일한 신호다.

보유기간을 늘리면 mean은 더 커지지만(12m +9.7% → 15m +12.0% → 18m +22.4%) **median은
15m부터 마이너스로 돌아선다**(-2.7%) — 평균은 소수 대박 종목이 끌어올리는 구조이므로,
포지션은 12m 관점으로 보수적으로 잡는다.

---

## 5. 폐기한 조합 (간단히)

| 신호 | 결과 | 폐기 이유 |
|------|------|-----------|
| per_ratio < 0.5 단독 | alpha -10.3%/median -9.9% | 유틸·지주 제외 후 baseline보다 나쁨 |
| acceleration ≥ 2 단독 (상한 없음) | alpha -0.3%/median -3.7% | 좋은 구간(2~5)과 나쁜 구간(5+)이 섞여 신호 희석 |
| capex_g1 (전년비 증감) | 22.6% vs 25.5% (raw), 차이 없음 | 완전 무의미, 두 차례 검증에서 재확인 |
| FCF 부호 | 검증 시점마다 방향이 뒤집힘 | 노이즈로 판단, 안정적 패턴 아님 |
| rev_1y↓(매출 역성장) + capex 감소 + 저평가 조합 | 3팩터 그리드 1위(alpha mean +36.2%)지만 median -3.8% | mean만 높고 median 마이너스 — 소수 대박 종목 주도, "성장주" 취지와도 반대(매출 역성장이 좋다는 논리) |

자세한 원본 수치는 `methodology/large_growth_pit_signal_verify.md`(raw/alpha 비교 과정)와
`methodology/large_growth_pit_factor_grid.md`(30개 팩터 그리드서치)에 남겨둔다.

---

## 6. 매수 기준

```
매수: 0.5 ≤ per_ratio < 1.0  AND  2 ≤ acceleration < 5
      → alpha mean +9.7%, median +2.1%(n=162)

해당 없음 → 매수 없음. 특히 per_ratio < 0.5(극단 저평가)나
acceleration ≥ 5(급가속)를 "더 좋은 신호"로 착각하지 않는다 — 둘 다 오히려 나쁘다.
```

---

## 7. 홀딩/매도 기준

```
per_ratio < 1.5           →  홀딩
per_ratio ≥ 1.5           →  매도 검토
per_ratio ≥ 2.0           →  매도 (하방 위험 명확: median -9.5%, <-20% 비율 37%, raw 기준)
acceleration ≥ 5로 진입   →  가속이 아니라 기저효과 가능성 — 매도 트리거는 아니지만 재평가
```

---

## 8. 미결 사항

```
- n=162는 이전보다 낫지만 out-of-sample 검증은 아직 안 했다 — 시간 경과로 이벤트가
  쌓이면 재확인.
- 15m/18m median이 마이너스로 돌아서는 이유(소수 종목 주도)를 종목 단위로 아직
  분해해보지 않았다.
- 이전 신호(per_ratio<0.5 + accel≥2) 기준으로 작성됐던 종목별 분석 문서는 이번 개정으로
  폐기했다. 확정 신호(§3) 기준 종목별 판단은 아직 다시 작성하지 않았다.
```

---

*run_id=5 / as_of=2026-07-22 / 확정 신호: ratio[0.5,1.0) + accel[2,5), growth_pit16, alpha(KOSPI200) 기준*
*재현: `.venv/bin/python scripts/simulate/verify_growth_signal.py`*
