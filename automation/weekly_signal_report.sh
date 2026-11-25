#!/bin/bash
# 주간 매수·매도 신호 리포트 — 매주 일요일 18:00.
#
# 토요일 12:00 잠정실적 이후, 월요일 장 전에 돌린다. 가격 기준은 직전 거래일
# 종가(보통 금요일)다. 글 작성은 Cursor agent CLI가
# automation/prompts/weekly_signal_report_prompt.md 절차로 하고, 검토 없이
# docs/signal_reports/<날짜>.md 와 docs/index.html 만 commit+push 한다.
# 2026-10-17: 화요일 수동·검토 후 발행을 이 잡으로 바꿨다.
#
# 사용법: automation/weekly_signal_report.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

LOG_DIR="$ROOT/automation/logs"
mkdir -p "$LOG_DIR"
TODAY="$(TZ=Asia/Seoul date +%Y-%m-%d)"
LOG_FILE="$LOG_DIR/$(TZ=Asia/Seoul date +%Y%m%d)_weekly.log"

find_agent() {
    if command -v agent >/dev/null 2>&1; then
        command -v agent
        return
    fi
    local candidate
    for candidate in "$HOME/.local/bin/agent" "/Applications/Cursor.app/Contents/Resources/app/bin/agent"; do
        if [[ -x "$candidate" ]]; then
            echo "$candidate"
            return
        fi
    done
    return 1
}

prelim_ok() {
    local f="$1"
    [[ -f "$f" ]] || return 1
    grep -q "preliminary_earnings_update 완료" "$f" || return 1
    if grep -q "Traceback" "$f"; then
        return 1
    fi
    if grep -q '"status":"800"' "$f" || grep -q '"status":"020"' "$f"; then
        return 1
    fi
    return 0
}

{
    echo "===== weekly_signal_report 시작 $(date '+%Y-%m-%d %H:%M:%S') ====="

    if [[ -f "docs/signal_reports/${TODAY}.md" ]]; then
        echo "오늘 리포트가 이미 있음 — 작성 생략 (${TODAY})"
        echo "===== weekly_signal_report 완료 $(date '+%Y-%m-%d %H:%M:%S') ====="
        exit 0
    fi

    SATURDAY="$("$PY" - <<'PY'
from datetime import date, timedelta
today = date.today()
delta = (today.weekday() - 5) % 7
print((today - timedelta(days=delta)).strftime("%Y%m%d"))
PY
)"
    PRELIM_LOG="$LOG_DIR/${SATURDAY}_preliminary.log"
    echo "잠정실적 로그: $PRELIM_LOG"
    if ! prelim_ok "$PRELIM_LOG"; then
        echo "잠정실적 수집이 없거나 실패 — 한 번 다시 실행"
        bash "$ROOT/automation/preliminary_earnings_update.sh"
        PRELIM_LOG="$LOG_DIR/$(TZ=Asia/Seoul date +%Y%m%d)_preliminary.log"
        if ! prelim_ok "$PRELIM_LOG"; then
            echo "잠정실적 재수집 실패 — 리포트를 쓰지 않음"
            exit 1
        fi
        "$PY" scripts/build_dashboard.py
    fi

    AGENT="$(find_agent)" || {
        echo "Cursor agent CLI(agent)가 없음. 일요일 리포트 본문을 쓸 수 없다."
        echo "설치: curl https://cursor.com/install -fsS | bash"
        exit 1
    }
    echo "agent: $AGENT"

    "$AGENT" -p --force --trust --workspace "$ROOT" \
        "automation/prompts/weekly_signal_report_prompt.md 를 처음부터 끝까지 읽고 그대로 실행하라. 오늘은 ${TODAY} 이고, 스케줄러가 호출한 무인 실행이다. 사용자에게 검토를 요청하지 마라. 리포트를 docs/signal_reports/${TODAY}.md 에 저장하고 대시보드를 재생성한 뒤, 그 파일과 docs/index.html 만 커밋하고 origin main 에 push 하라. 커밋 전에 git pull --rebase origin main. force push 금지. 다른 파일은 커밋하지 마라. 커밋 메시지: auto: weekly signal report ${TODAY}"

    if [[ ! -f "docs/signal_reports/${TODAY}.md" ]]; then
        echo "리포트 파일이 없다: docs/signal_reports/${TODAY}.md"
        exit 1
    fi

    "$PY" scripts/build_dashboard.py
    git pull --rebase origin main
    git add -- "docs/signal_reports/${TODAY}.md" docs/index.html
    if git diff --cached --quiet; then
        echo "커밋할 변경 없음 — 이미 push 됐을 수 있음"
    else
        git commit -m "auto: weekly signal report ${TODAY}"
        git push origin main
        echo "git push 완료"
    fi

    echo "===== weekly_signal_report 완료 $(date '+%Y-%m-%d %H:%M:%S') ====="
} >> "$LOG_FILE" 2>&1
