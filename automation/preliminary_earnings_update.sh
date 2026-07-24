#!/bin/bash
# 잠정실적(공정공시) 얼리 시그널 수집 — 매주 자동 실행.
#
# scripts/pipeline/collect_preliminary_earnings.py 를 인자 없이 호출 —
# automation/quarterly_term_window.py 의 preliminary_target_term() 이 오늘
# 날짜로 "분기 마감 전 잠정실적이 올라올 수 있는 창"인지 자동 판단한다(창
# 밖이면 DART를 부르지 않고 바로 스킵). 창 안이면 top-n 200 종목의 DART
# 공시 목록에서 "잠정실적" 공시를 찾아 매출액·영업이익(+가능하면 당기순이익)을
# 파싱해 data/analytics/preliminary_earnings.db 에 적재한다.
#
# 정식 재무제표(CFO·자산·자본·주식수 등)는 여기서 안 나온다 — 그건 마감일
# 기준으로 도는 automation/quarterly_financial_update.sh 담당. 이 스크립트는
# 순수 얼리 시그널 보조 트랙이라 대시보드 파이프라인에 연결돼 있지 않다.
#
# data/analytics/ 는 .gitignore 대상이라 git commit/push 없음.
#
# 사용법: automation/preliminary_earnings_update.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

LOG_DIR="$ROOT/automation/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y%m%d)_preliminary.log"

{
    echo "===== preliminary_earnings_update 시작 $(date '+%Y-%m-%d %H:%M:%S') ====="
    "$PY" scripts/pipeline/collect_preliminary_earnings.py
    echo "===== preliminary_earnings_update 완료 $(date '+%Y-%m-%d %H:%M:%S') ====="
} >> "$LOG_FILE" 2>&1

echo "완료 — 로그: $LOG_FILE"
tail -5 "$LOG_FILE"
