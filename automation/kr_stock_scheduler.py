#!/usr/bin/env python3
"""
로컬 가격·재무·대시보드 스케줄러 — 터미널을 켜둔 채로 계속 실행해두는 방식
(us-stock-portfolio의 automation/scheduler_data_collection.py 와 동일 원칙).

실행:
    caffeinate -i .venv/bin/python automation/kr_stock_scheduler.py

동작 (3개 잡):
  - 매일 KST 16:00(장 마감 15:30 이후 여유): daily_update.sh
    (가격 → 팩터 패널 → PIT 버킷 → 대시보드 → 변경 있으면 git push)
  - 매일 KST 09:00: quarterly_financial_update.sh (정식 분기·반기·사업보고서,
    인자 없이 — automation/quarterly_term_window.py의 formal_target_term()이
    "마감일+1일 또는 마감일+8일"에만 값을 주고 그 외엔 스킵 — 마감일 당일은
    그날 늦게 내는 곳을 놓칠 수 있어 하루 늦춰서 확인한다). 요일이 아니라
    날짜(마감일 5/15·8/15·11/15·3/31 기준 +1/+8일)로 트리거되므로 매일
    체크해야 한다 — 그 날짜가 항상 월요일인 건 아니기 때문.
  - 매주 토요일 KST 12:00: preliminary_earnings_update.sh (잠정실적 얼리
    시그널, preliminary_target_term()의 넓은 창 — 분기 마감 전 회사마다
    흩어져서 올라오는 공시를 매주 다시 훑어서 채운다). 실패하면(DART 점검 등)
    3시간 간격으로 최대 2번 재시도한다 — 잠정실적은 대시보드 밸류매수 판정에
    들어가므로 빠지면 주간 리포트 전에 메워야 한다(2026-10-10 점검으로 실패한 사례).

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

놓친 실행 따라잡기: 잡별 마지막 실행 날짜를 automation/logs/scheduler_state.json
에 저장해서, 맥이 잠들어 있었거나 스케줄러를 재시작해 정해진 시각을 놓쳤으면
깨어난 직후 바로 실행한다(데일리는 그날 16:00 이후, 잠정실적은 그 주 토요일
12:00 이후). 분기 재무는 트리거 날짜(마감+1/+8일)를 통째로 놓쳤어도 최근
QUARTERLY_CATCHUP_DAYS일 안이면 그 분기를 연·분기 인자로 지정해 실행한다.

Ctrl+C로 종료.
"""

import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from quarterly_term_window import formal_target_term  # noqa: E402

DAILY_SCRIPT = ROOT / "automation" / "daily_update.sh"
QUARTERLY_SCRIPT = ROOT / "automation" / "quarterly_financial_update.sh"
PRELIMINARY_SCRIPT = ROOT / "automation" / "preliminary_earnings_update.sh"
LOG_FILE = ROOT / "automation" / "logs" / "scheduler.log"
# 잡별 마지막 실행 날짜 — 재시작·잠자기 후에도 놓친 실행을 따라잡기 위해 저장
STATE_FILE = ROOT / "automation" / "logs" / "scheduler_state.json"

DAILY_HOUR = 16
DAILY_MINUTE = 0

QUARTERLY_HOUR = 9
QUARTERLY_MINUTE = 0
QUARTERLY_CATCHUP_DAYS = 30  # 이보다 오래 꺼져 있었으면 놓친 트리거 날짜를 따라잡지 않음(수동 실행)

PRELIMINARY_WEEKDAY = 5  # 토요일 (월=0 ... 일=6)
PRELIMINARY_HOUR = 12
PRELIMINARY_MINUTE = 0

PRELIMINARY_RETRY_DELAY = timedelta(hours=3)
PRELIMINARY_MAX_RETRIES = 2

CHECK_INTERVAL_SEC = 20


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run(script: Path, name: str, *args: str) -> bool:
    log(f"{name} 실행 시작")
    try:
        subprocess.run(["bash", str(script), *args], check=True)
        log(f"{name} 완료")
        return True
    except subprocess.CalledProcessError as e:
        log(f"{name} 실패 (exit {e.returncode}) — 상세는 automation/logs/*.log 참조")
        return False


def load_state() -> dict[str, date]:
    try:
        raw = json.loads(STATE_FILE.read_text())
        return {k: date.fromisoformat(v) for k, v in raw.items()}
    except (FileNotFoundError, ValueError):
        return {}


def save_state(state: dict[str, date]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({k: v.isoformat() for k, v in state.items()}, indent=2))


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)


def latest_preliminary_slot(now: datetime) -> datetime:
    """now 이전(포함) 가장 최근의 토요일 12:00."""
    days_back = (now.weekday() - PRELIMINARY_WEEKDAY) % 7
    slot = at(now.date() - timedelta(days=days_back), PRELIMINARY_HOUR, PRELIMINARY_MINUTE)
    return slot if slot <= now else slot - timedelta(days=7)


def missed_quarterly_terms(last: date | None, now: datetime) -> tuple[list[str], date]:
    """last 다음날부터 오늘(09:00 지났으면)까지 중 트리거 날짜(마감+1/+8일)에 해당하는 분기들.
    반환: (실행할 분기 목록, 체크 완료로 기록할 마지막 날짜)."""
    end = now.date() if now >= at(now.date(), QUARTERLY_HOUR, QUARTERLY_MINUTE) else now.date() - timedelta(days=1)
    start = max(
        (last + timedelta(days=1)) if last else end,
        now.date() - timedelta(days=QUARTERLY_CATCHUP_DAYS),
    )
    terms: list[str] = []
    d = start
    while d <= end:
        term = formal_target_term(d)
        if term and term not in terms:
            terms.append(term)
        d += timedelta(days=1)
    return terms, end


def main() -> None:
    log(
        f"스케줄러 시작 — 매일 KST {DAILY_HOUR:02d}:{DAILY_MINUTE:02d} daily_update, "
        f"매일 KST {QUARTERLY_HOUR:02d}:{QUARTERLY_MINUTE:02d} quarterly_financial_update(마감일+1/+8일에만 실행), "
        f"매주 토요일 KST {PRELIMINARY_HOUR:02d}:{PRELIMINARY_MINUTE:02d} preliminary_earnings_update. "
        "시각을 놓쳤으면(잠자기·재시작) 깨어난 뒤 따라잡는다. Ctrl+C로 종료."
    )
    state = load_state()
    preliminary_retry_at = None
    preliminary_retries = 0

    try:
        while True:
            now = datetime.now()

            if now >= at(now.date(), DAILY_HOUR, DAILY_MINUTE) and state.get("daily") != now.date():
                state["daily"] = now.date()
                save_state(state)
                run(DAILY_SCRIPT, "daily_update")

            terms, checked_until = missed_quarterly_terms(state.get("quarterly"), now)
            if state.get("quarterly") != checked_until:
                state["quarterly"] = checked_until
                save_state(state)
                for term in terms:
                    run(QUARTERLY_SCRIPT, f"quarterly_financial_update {term}", term[:4], term[-1])

            slot = latest_preliminary_slot(now)
            last_prelim = state.get("preliminary")
            if last_prelim is None or last_prelim < slot.date():
                state["preliminary"] = now.date()
                save_state(state)
                preliminary_retries = 0
                preliminary_retry_at = None
                if not run(PRELIMINARY_SCRIPT, "preliminary_earnings_update"):
                    preliminary_retry_at = datetime.now() + PRELIMINARY_RETRY_DELAY
                    log(f"preliminary_earnings_update 재시도 예약 {preliminary_retry_at:%m-%d %H:%M}")

            if preliminary_retry_at is not None and now >= preliminary_retry_at:
                preliminary_retries += 1
                if run(PRELIMINARY_SCRIPT, f"preliminary_earnings_update 재시도 {preliminary_retries}/{PRELIMINARY_MAX_RETRIES}"):
                    preliminary_retry_at = None
                elif preliminary_retries < PRELIMINARY_MAX_RETRIES:
                    preliminary_retry_at = datetime.now() + PRELIMINARY_RETRY_DELAY
                    log(f"preliminary_earnings_update 재시도 예약 {preliminary_retry_at:%m-%d %H:%M}")
                else:
                    preliminary_retry_at = None
                    log("preliminary_earnings_update 재시도 모두 실패 — 주간 리포트 전에 수동 재수집 필요")

            time.sleep(CHECK_INTERVAL_SEC)
    except KeyboardInterrupt:
        log("스케줄러 종료 (Ctrl+C)")


if __name__ == "__main__":
    main()
