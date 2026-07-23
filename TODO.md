# TODO

## 1. 매수 추천 리포트
확정 신호 4개(성장/밸류 × 매수/매도, docs/large_growth_selection_strategy.md·
large_value_selection_strategy.md)로 "지금 실제로 사야/팔아야 할 종목"을 정리하는
리포트. us-stock-portfolio의 docs/buy_signal_reports/*.md 참고. 대시보드 메인
테이블의 매수/매도 태그(현재 6종목 매수, 13종목 매도 — 2026Q1 기준)를 문장형으로
정리하는 형태가 될 듯.

## 2. 가격·재무 데이터 스케줄링
- 가격(매일 갱신): `scripts/build_current_prices.py` → `data/analytics/current_prices.csv`,
  `data/analytics/prices.db`
- 재무(분기, DART 공시 시점에만): 분기 원천 재적재(`scripts/pipeline/update_quarter_dbs.py`
  등) → `scripts/pipeline/populate_ttm_valuation.py` → `scripts/analysis/build_mcap200_factor_panel.py`
  → `scripts/analysis/build_pit_buckets.py`
- us-stock-portfolio의 `automation/daily_update.sh`(cron/launchd) 구조를 KR용으로
  가져와서 구성 — 가격은 매일, 재무는 분기 공시 시점에만 도는 별도 트랙으로 분리

## 3. 신호 스케줄링
데이터 갱신 후 `scripts/build_dashboard.py` 재실행 → `docs/index.html` 재생성 →
자동 커밋·푸시(GitHub Pages 자동 재배포, https://idea-hwan.github.io/kr-stock-portfolio/).
2번 스케줄링과 묶어서 한 파이프라인으로 구성.
