#!/bin/bash
# 매일 자동 갱신 (가격 → 패널·PIT 재계산 → 대시보드 → GitHub Pages 업로드)
#   1. 가격 증분 수집 (data/analytics/prices.db)
#   2. 현재가·trailing 수익률 캐시 (data/analytics/current_prices.csv)
#   3. mcap200 팩터 패널 재계산 (data/analytics/mcap200_factor_panel.csv)
#   4. PIT 버킷 재계산 (data/analytics/pit_buckets.db)
#   5. 대시보드(docs/index.html) 재생성
#   6. 변경 있으면 git commit + push (GitHub Pages 자동 갱신)
#
# 재무 원본 적재(DART, update_quarter_dbs.py 등)는 여기 없음 — 연·분기 인자와
# 사람 판단(이름변경·신규백필·오딧 검토)이 필요해서 automation/quarterly_financial_update.sh
# 로 분리했다. 그 스크립트가 갱신한 ttm_valuation.db는 다음 날 이 스크립트의
# 3~5단계(패널·PIT·대시보드)에서 자동으로 반영된다.
#
# data/analytics/ 산출물은 전부 .gitignore 대상이라 git에는 docs/index.html만 올라간다.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

LOG_DIR="$ROOT/automation/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y%m%d)_daily.log"

{
    echo "===== daily_update 시작 $(date '+%Y-%m-%d %H:%M:%S') ====="
    "$PY" scripts/pipeline/collect_prices.py
    "$PY" scripts/build_current_prices.py
    "$PY" scripts/analysis/build_mcap200_factor_panel.py
    "$PY" scripts/analysis/build_pit_buckets.py
    "$PY" scripts/build_dashboard.py

    if [[ -n "$(git status --porcelain -- docs/index.html)" ]]; then
        git add docs/index.html
        git commit -m "auto: dashboard update $(date '+%Y-%m-%d %H:%M')"
        git push origin main
        echo "git push 완료"
    else
        echo "변경 사항 없음 — git push 스킵"
    fi

    echo "===== daily_update 완료 $(date '+%Y-%m-%d %H:%M:%S') ====="
} >> "$LOG_FILE" 2>&1
