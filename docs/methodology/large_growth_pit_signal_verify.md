# 대형 성장주 — 기존 신호(per_ratio × acceleration), 16분기 vs 28분기 (PIT 고정)

> 작성일 2026-07-22, **2026-07-22 유틸/지주 제외 반영으로 갱신**. `large_growth_selection_strategy.md`
> (run_id=1, as_of=2025Q4)가 쓴 **기존 신호 정의**(per_ratio, acceleration)는 그대로 두고, "연속
> 흑자 몇 분기를 버킷 조건으로 볼지"(16분기 vs 28분기)만 비교한다. **PIT 교정은 둘 다 기본으로
> 적용** — naive(오늘 통과 종목만) 비교가 아니다. `large_growth_pit_factor_grid.md`(28개 이진 팩터
> 그리드서치, 이 갱신 이전 유니버스로 아직 미재실행)와도 다르다 — 저건 새 신호 탐색, 이건 기존
> 신호의 분기 임계값 재검증.
>
> **갱신 이력**: 최초 작성 시 유니버스에 한국전력·한국가스공사·SK·LG·GS 등 유틸리티·지주회사가
> 섞여 있었다. `scripts/stock_db.py`에 `utility_sector_exclusion_mask`/`holding_company_exclusion_mask`
> 를 추가해 이들을 mcap200 유니버스에서 제외하고 `mcap_top_200.csv` → `mcap200_factor_panel.csv` →
> `pit_buckets16`/`pit_buckets28`을 전부 재생성한 뒤 이 문서를 다시 썼다. **아래 숫자는 전부
> 제외 반영 후 값이며, §4의 결론이 이전 버전과 달라졌다** — 자세한 건 `large_growth_selection_strategy.md`
> (run_id=3)를 참고.

재현:
```
.venv/bin/python scripts/pipeline/export_mcap_top_200.py                 # 유틸/지주 제외 반영 mcap_top_200.csv
.venv/bin/python scripts/analysis/build_mcap200_factor_panel.py           # 팩터 패널 재생성
.venv/bin/python scripts/analysis/build_pit_buckets.py                    # pit_buckets16
.venv/bin/python scripts/analysis/build_pit_buckets.py --min-q 28         # pit_buckets28
.venv/bin/python scripts/simulate/verify_growth_signal.py
```

---

## 1. 방법론

- **Signal A (저평가)**: `per_ratio = per_op_20d / per_op_4y` (op → ni → rev 폴백)
- **Signal B (성장 가속)**: `acceleration = op_geom_1y_mcum / op_geom_4y_mcum`
- 유니버스는 두 경우 모두 PIT 롤링 재판정(`build_pit_buckets.py`, `rolling_all_positive`) —
  "그 분기 시점까지의 데이터만으로 최근 N분기 연속 `op_ps > 0`였는가"를 N=16, N=28
  각각에 대해 계산한 `growth_pit16`/`growth_pit28`. 유니버스는 `mcap_top_200.csv`
  (유틸리티·지주회사 제외 반영판) 기준.
- 수익률은 원 문서와 동일하게 **원시(raw) 수익률**(alpha 아님).

### 1.1 함정 — 기간 불일치

28분기 연속 흑자를 확인하려면 최소 7년치 데이터가 필요해서, `growth_pit28`은 데이터가
쌓인 **최근 구간에서만** 플래그가 켜진다. 그냥 두 버킷을 비교하면 "28분기가 더 좋다"가
아니라 "최근 강세장 구간만 본 것"이 될 수 있다 — 아래 §2에서 먼저 이 문제를 확인하고,
§3에서 기간을 맞춰 재비교한다.

| | n(종목) | n(이벤트) | term |
|---|---|---|---|
| growth_pit16 | 141 | 2,468 | 2020Q3~2026Q1 |
| growth_pit28 | 106 | 983 | **2023Q3~2026Q1** |

(유틸/지주 제외 전: growth_pit16 147종목/2,608, growth_pit28 112종목/1,061 — 제외로 종목·이벤트가
소폭 줄었다.)

---

## 2. 원구간 그대로 비교 (기간 안 맞춤 — 오해 주의)

| | n | baseline mean | baseline median | 핵심신호(ratio<0.5+accel≥2) n | mean | median |
|---|---|---|---|---|---|---|
| PIT-16 | 2468 | +22.4% | -0.2% | 104 | +15.1% | -2.7% |
| PIT-28 | 983 | **+35.4%** | +8.9% | 24 | +34.6% | +6.3% |

언뜻 28분기 쪽이 baseline부터(+35.4% vs +22.4%) 훨씬 높아 보이지만, 이건 §1.1에서 지적한
기간 문제 그대로다 — PIT-28은 2023Q3 이후만 존재해서 최근 강세장이 그대로 baseline에
반영된 것.

---

## 3. 기간 맞춰 재비교 (2023Q3~2026Q1, 공정한 비교)

PIT-16도 동일하게 2023Q3 이후로 잘라서 다시 봤다.

| | n(종목) | n(이벤트) | baseline mean | baseline median | 핵심신호 n | mean | median | baseline 대비 우위(mean) |
|---|---|---|---|---|---|---|---|---|
| PIT-16 (2023Q3~) | 132 | 1220 | +38.7% | +9.5% | 28 | +32.3% | +6.3% | **-6.4%p** |
| PIT-28 (2023Q3~) | 106 | 983 | +35.4% | +8.9% | 24 | +34.6% | +6.3% | -0.8%p |

**기간을 맞추니 16분기와 28분기의 baseline 자체가 비슷해진다**(+38.7% vs +35.4%, 둘 다
같은 강세장 구간) — 이 부분은 이전 결론과 동일하다. 하지만 **핵심신호(ratio<0.5+accel≥2)가
이번엔 두 경우 모두 baseline을 밑돈다**(-6.4%p, -0.8%p). 유틸/지주 제외 전에는 두 경우 모두
baseline 대비 우위(+2.7%p, +5.6%p)를 보였던 것과 정반대다.

**결론: 16분기 vs 28분기 자체는 여전히 결과에 큰 차이를 만들지 않는다** — 이건 이전과
동일. 다만 **"per_ratio<0.5+accel≥2가 baseline보다 낫다"는 이전 결론은 유틸/지주 제외 후
성립하지 않는다.** 한국전력·SK·LG 등 유틸리티·지주회사가 구조적으로 낮은 PER를 갖는
경우가 많아서, 이들이 그동안 저평가(ratio<0.5) 버킷의 성과를 실제보다 부풀렸을 가능성이
크다 — 자세한 분석과 전략 문서 개정은 `large_growth_selection_strategy.md`(run_id=3) 참고.

---

## 4. 미해결/다음 단계 (§5 갱신 이후 상태)

1. n=24~28은 여전히 작아서 표본 노이즈 가능성을 배제 못 함 — 표본이 더 쌓이거나(시간
   경과), 다른 신호 조합으로도 같은 패턴(핵심신호가 baseline을 못 이김)이 재현되는지 확인
   필요.
2. ~~이 문서는 raw 수익률만 봤다~~ → §5에서 alpha 반영 완료. **결론이 raw와 정반대다.**
3. ~~`large_growth_pit_factor_grid.md`는 아직 유틸/지주 제외 이전 유니버스~~ → 재실행·갱신
   완료(2026-07-22).
4. `pit_buckets16`/`pit_buckets28` 테이블은 유틸/지주 제외 반영해 재생성 완료
   (`pit_buckets.db`) — `mcap_top_200.csv`가 갱신되면 다시 재생성 필요.
5. §5에서 새로 발견한 `ratio 0.5~1.0 + accel[2,5)` 리드는 아직 out-of-sample 검증이나
   보조 팩터(capex/FCF) 교차검증을 거치지 않았다 — `large_growth_selection_strategy.md`
   (run_id=4)에서 계속 추적.

---

## 5. 후속 갱신 (2026-07-22) — 16분기 단일화 + alpha 반영

이 문서의 §3 결론(16≈28, 16분기 채택)에 따라 `verify_growth_signal.py`를 **16분기만
계산하도록 단순화**했다 — 더 이상 28분기 로직을 유지하지 않는다(`pit_buckets28` 테이블
자체는 남아있지만 이 스크립트는 더 이상 참조하지 않음). 동시에 raw 수익률만 보던 걸
**KOSPI200 대비 alpha**도 함께 출력하도록 바꿨다.

### raw vs alpha — 결론이 뒤집힌다

| | n | raw mean/median | alpha mean/median |
|---|---|---|---|
| 전체(baseline) | 2468 | +22.4% / -0.2% | **-8.5% / -10.5%** |
| ratio<0.5 (단독) | 345 | +15.7% / +0.5% | -10.3% / -9.9% |
| ratio<0.5 + accel≥2 | 104 | +15.1% / -2.7% | -4.1% / -8.5% |
| ratio<1.0 + accel≥2 | 408 | +20.8% / +1.6% | -1.5% / -3.9% |

이 유니버스 전체가 **raw로는 플러스(+22.4%)지만 같은 기간 KOSPI200에는 졌다**(alpha
-8.5%). 그리고 raw 기준으로는 baseline보다 나빴던 핵심신호(`ratio<0.5+accel≥2`,
-7.3%p)가 **alpha 기준으로는 오히려 baseline보다 낫다**(-4.1% vs -8.5%, +4.4%p).
`ratio<1.0+accel≥2`는 alpha 우위가 더 크다(+7.0%p). **raw 수익률 비교만으로 "신호가
죽었다"고 결론 낸 §3의 판단은 성급했다** — 상대적으로는 여전히 시장을 덜 잃는 효과가
있다. 다만 절대 alpha 자체는 여전히 마이너스라 "이걸 사면 시장을 이긴다"는 아니다.

### 새 리드 — acceleration을 구간(2~5)으로 좁히면 유일하게 alpha가 플러스

가속 구간별 alpha_12m: `<1.0` -10.5% · `1.0~2.0` -17.8%(최저) · **`2.0~5.0` +7.2%(유일한
플러스)** · `5.0+` -9.7%. 지금까지 쓰던 `accel≥2`(무제한 상한)는 좋은 구간(2~5)과 나쁜
구간(5+)을 섞어서 신호를 희석시키고 있었다.

`ratio 0.5~1.0 + accel[2,5)`로 좁히면: **n=162, alpha mean +9.7%, median +2.1%** — mean과
median이 둘 다 플러스인 몇 안 되는 조합이다(`large_growth_pit_factor_grid.md` §5의 상위
조합들은 대부분 mean만 플러스고 median은 마이너스). baseline(-8.5%) 대비 +18.2%p 우위.

| 조건 | n | alpha mean | alpha median |
|------|---|---|---|
| ratio<0.5 + accel[2,5) | 60 | -0.5% | -8.3% |
| **ratio 0.5~1.0 + accel[2,5)** | **162** | **+9.7%** | **+2.1%** |
| ratio 1.0~1.5 + accel[2,5) | 51 | +0.9% | -3.4% |
| ratio 1.5~2.0 + accel[2,5) | 20 | +28.5% | +3.1% |
| ratio 2.0+ + accel[2,5) | 7 | +0.3% | -25.7% |

`1.5~2.0` 구간은 mean이 가장 높지만 n=20으로 너무 작아 이상치일 가능성이 크다. `2.0+`도
n=7로 무의미. **`0.5~1.0 + accel[2,5)`(n=162)가 표본 크기 대비 가장 신뢰할 만한 후보다.**
아직 검증 안 된 것: out-of-sample 재현성, capex/FCF와 교차, 15m/18m 보유기간(§ 아래).

15m/18m(accel[2,5) 단독, ratio 필터 없이): alpha mean 12m +7.2% → 15m +7.9% → 18m
+16.9%로 보유기간이 늘수록 개선. 다만 median은 세 기간 다 마이너스(-3.4%/-6.4%/-5.2%)라
"평균은 좋지만 중앙값 종목은 여전히 시장에 진다" — 소수 대박 종목이 평균을 끄는 구조.

**결론**: raw 기준 §3의 "신호 없음" 판단은 alpha로 보면 과했다. 다만 새로 찾은
`ratio 0.5~1.0 + accel[2,5)`도 아직 "확정 신호"로 쓰기엔 이르다 — 후속 검증은
`large_growth_selection_strategy.md`(run_id=4)에서 이어간다.
