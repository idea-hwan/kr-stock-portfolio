# TODO

## 1. 매수 추천 리포트
확정 신호 4개(성장/밸류 × 매수/매도, docs/large_growth_selection_strategy.md·
large_value_selection_strategy.md)로 "지금 실제로 사야/팔아야 할 종목"을 정리하는
리포트. us-stock-portfolio의 docs/buy_signal_reports/*.md 참고. 대시보드 메인
테이블의 매수/매도 태그(현재 6종목 매수, 13종목 매도 — 2026Q1 기준)를 문장형으로
정리하는 형태가 될 듯.

## 2. 스케줄러 실제 가동 (2026-07-25)
스크립트·foreground 스케줄러는 2026-07-24에 다 만들고 검증까지 끝남(`automation/`,
커밋 `a980d9a`). 내일 할 일은 실제로 계속 돌리는 것 — 세 트랙:

- **데일리 가격**: `automation/daily_update.sh` (매일 18:00) — 가격→팩터패널→PIT→
  대시보드 재생성 → 변경 있으면 자동 commit+push (`docs/index.html`, GitHub Pages
  자동 재배포)
- **주간 잠정실적**: `automation/preliminary_earnings_update.sh` (매주 월요일 09:05) —
  정식 공시 전 "영업(잠정)실적" 조기 반영, `data/analytics/preliminary_earnings.db`
- **분기 재무 데이터(DB 포함)**: `automation/quarterly_financial_update.sh` (마감일
  +1일/+8일 09:00) — DART 정식 분기·반기·사업보고서 → 분기 원천 DB(`data/financial_statement/`,
  `data/dividend/`, `data/stocks/`) 재적재 → `mcap_top_200.csv` 갱신 → TTM·PER
  재계산까지 한 번에

세 트랙 다 `automation/scheduler.py` 하나로 묶여있음 —
`caffeinate -i .venv/bin/python automation/scheduler.py` 로 켜서 터미널에 계속
띄워둘지, launchd로 상시 서비스화할지만 정하면 됨.
