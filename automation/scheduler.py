#!/usr/bin/env python3
"""
로컬 가격·재무·대시보드 스케줄러 — 터미널을 켜둔 채로 계속 실행해두는 방식
(us-stock-portfolio의 automation/scheduler_data_collection.py 와 동일 원칙).

실행:
    caffeinate -i .venv/bin/python automation/scheduler.py

동작 (3개 잡):
  - 매일 KST 18:00(장 마감 15:30 이후 여유): daily_update.sh
    (가격 → 팩터 패널 → PIT 버킷 → 대시보드 → 변경 있으면 git push)
  - 매일 KST 09:00: quarterly_financial_update.sh (정식 분기·반기·사업보고서,
    인자 없이 — automation/quarterly_term_window.py의 formal_target_term()이
    "마감일+1일 또는 마감일+8일"에만 값을 주고 그 외엔 스킵 — 마감일 당일은
    그날 늦게 내는 곳을 놓칠 수 있어 하루 늦춰서 확인한다). 요일이 아니라
    날짜(마감일 5/15·8/15·11/15·3/31 기준 +1/+8일)로 트리거되므로 매일
    체크해야 한다 — 그 날짜가 항상 월요일인 건 아니기 때문.
  - 매주 월요일 KST 09:00: preliminary_earnings_update.sh (잠정실적 얼리
    시그널, preliminary_target_term()의 넓은 창 — 분기 마감 전 회사마다
    흩어져서 올라오는 공시를 매주 다시 훑어서 채운다).

두 재무 잡 모두 활성 창/날짜가 아니면 DART를 부르지 않고 스스로 스킵하므로
매일 호출해도 안전하다.

KR 프로젝트는 US와 달리 실행 시각과 시장 시간대가 같은 KST라 요일별 분기
로직이 필요 없다 — 주말·휴장일엔 새 가격이 없어 대부분 스크립트가 사실상
no-op으로 끝나고, docs/index.html에 diff가 없으면 daily_update.sh가 알아서
git push를 스킵한다.

A3(이름변경)·A4(신규백필)처럼 판단이 필요한 예외 처리는 여기 포함하지 않는다
— quarterly_financial_update.sh 의 A5 오딧 로그를 사람이 주기적으로 검토해서
필요할 때 직접 실행한다.

상세 로그는 automation/logs/YYYYMMDD_{daily,quarterly,preliminary}.log 에
쌓인다. 이 스크립트는 "언제 뭘 실행했는지"만 automation/logs/scheduler.log
에 기록한다.

Ctrl+C로 종료.
"""

import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DAILY_SCRIPT = ROOT / "automation" / "daily_update.sh"
QUARTERLY_SCRIPT = ROOT / "automation" / "quarterly_financial_update.sh"
PRELIMINARY_SCRIPT = ROOT / "automation" / "preliminary_earnings_update.sh"
LOG_FILE = ROOT / "automation" / "logs" / "scheduler.log"

DAILY_HOUR = 18
DAILY_MINUTE = 0

QUARTERLY_HOUR = 9
QUARTERLY_MINUTE = 0

PRELIMINARY_WEEKDAY = 0  # 월요일 (월=0 ... 일=6)
PRELIMINARY_HOUR = 9
PRELIMINARY_MINUTE = 5  # quarterly와 겹치지 않게 5분 뒤

CHECK_INTERVAL_SEC = 20


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run(script: Path, name: str) -> None:
    log(f"{name} 실행 시작")
    try:
        subprocess.run(["bash", str(script)], check=True)
        log(f"{name} 완료")
    except subprocess.CalledProcessError as e:
        log(f"{name} 실패 (exit {e.returncode}) — 상세는 automation/logs/*.log 참조")


def main() -> None:
    log(
        f"스케줄러 시작 — 매일 KST {DAILY_HOUR:02d}:{DAILY_MINUTE:02d} daily_update, "
        f"매일 KST {QUARTERLY_HOUR:02d}:{QUARTERLY_MINUTE:02d} quarterly_financial_update(마감일+1/+8일에만 실행), "
        f"매주 월요일 KST {PRELIMINARY_HOUR:02d}:{PRELIMINARY_MINUTE:02d} preliminary_earnings_update. "
        "Ctrl+C로 종료."
    )
    last_daily_date = None
    last_quarterly_date = None
    last_preliminary_date = None

    try:
        while True:
            now = datetime.now()

            if now.hour == DAILY_HOUR and now.minute == DAILY_MINUTE and last_daily_date != now.date():
                run(DAILY_SCRIPT, "daily_update")
                last_daily_date = now.date()

            if (
                now.hour == QUARTERLY_HOUR
                and now.minute == QUARTERLY_MINUTE
                and last_quarterly_date != now.date()
            ):
                run(QUARTERLY_SCRIPT, "quarterly_financial_update")
                last_quarterly_date = now.date()

            if (
                now.weekday() == PRELIMINARY_WEEKDAY
                and now.hour == PRELIMINARY_HOUR
                and now.minute == PRELIMINARY_MINUTE
                and last_preliminary_date != now.date()
            ):
                run(PRELIMINARY_SCRIPT, "preliminary_earnings_update")
                last_preliminary_date = now.date()

            time.sleep(CHECK_INTERVAL_SEC)
    except KeyboardInterrupt:
        log("스케줄러 종료 (Ctrl+C)")


if __name__ == "__main__":
    main()
