# TODO

## 1. 매수·매도 신호 리포트 — 프롬프트 준비 완료 (2026-07-27), 첫 실행 대기
us-stock-portfolio의 방식(`automation/prompts/weekly_buy_signal_report_prompt.md`)을
리뷰해서 그대로 이식 — `automation/prompts/weekly_signal_report_prompt.md`.
`docs/index.html`의 `buy`/`sell` 태그 종목을 숫자 1차 스크리닝 → WebSearch 뉴스
검증 → 최종 후보/고위험/제외로 분류해 `docs/signal_reports/YYYY-MM-DD.md`에 저장.
US와 다른 점: 매수뿐 아니라 매도 신호도 같은 4단계로 검증(사용자 확인), 버킷별로
매수 공식이 다름(성장=저평가+가속, 밸류=저평가+이익품질 — 매도는 공통).

완전 수동 워크플로우 — 자동 스케줄러 아님, 커밋·푸시 전 사람이 반드시 검토
(us-stock-portfolio와 동일 원칙). 다음 할 일: 사용자가 요청하면 프롬프트대로
실행해서 첫 회차 리포트 작성 → 몇 주 수동으로 발행하며 지켜보기.

## 2. 스케줄러 실제 가동 — 완료 (2026-07-27)
`automation/kr_stock_scheduler.py` 하나로 세 트랙 묶어서
`caffeinate -i .venv/bin/python automation/kr_stock_scheduler.py` 로 터미널에
계속 띄워둠 (다른 프로젝트 scheduler.py들과 구분하려고 파일명도 변경).

- **데일리 가격**: `automation/daily_update.sh` (매일 16:00) — 가격→팩터패널→PIT→
  대시보드 재생성 → 변경 있으면 자동 commit+push (`docs/index.html`, GitHub Pages
  자동 재배포)
- **분기 재무 데이터(DB 포함)**: `automation/quarterly_financial_update.sh` (매일
  09:00 체크, 실제 실행은 마감일+1일/+8일에만) — DART 정식 분기·반기·사업보고서 →
  분기 원천 DB(`data/financial_statement/`, `data/dividend/`, `data/stocks/`)
  재적재 → `mcap_top_200.csv` 갱신 → TTM·PER 재계산까지 한 번에. A1 실행 때 신규
  상장 코드 감지되면 `stock_data/new_codes_since_stock_csv.txt`에 자동 append,
  로그에 리마인더 출력 — 실제 백필(`backfill_new_listing.py`)은 여전히 수동 판단.
- **주간 잠정실적**: `automation/preliminary_earnings_update.sh` (매주 토요일
  12:00) — 정식 공시 전 "영업(잠정)실적" 조기 반영, `data/analytics/preliminary_earnings.db`

상세 사용법: [automation_usage.md](automation_usage.md)
