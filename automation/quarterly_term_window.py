"""
DART 정기공시 마감(1분기 5/15, 반기 8/15, 3분기 11/15, 사업보고서 3/31) 기준으로
"오늘 무슨 분기를 걷어야 하는지" 두 가지 창(window)을 판단한다.

왜 두 가지인가 (2026-07-24 삼성전자로 실측 확인):
  - 정식 분기·반기·사업보고서(finstate_all API)는 대형주도 마감일 당일에
    몰아서 내는 경우가 흔하다(삼성전자 2026Q1: 5/15 당일 제출). 마감일 한참
    전에 매주 다시 불러봐야 계속 비어 있을 뿐이라 낭비 — 그래서 formal_target_term()
    은 "마감일 다음날"(그날 하루치 제출이 전부 DART에 올라온 뒤 확인 — 당일
    체크는 그날 늦게 제출한 곳을 놓칠 수 있어 하루 늦춤) 또는 "마감일+8일
    (지각 제출 정리용)" 딱 두 시점에만 값을 준다.
  - 반면 "잠정실적(공정공시)"는 분기 마감 후 약 2~4주 사이에 회사마다 흩어져서
    올라온다(삼성전자 2026Q2: 7/7 제출, 마감 8/15보다 5주 이상 빠름). 이건 창이
    열려 있는 동안 매주 다시 걸어야 그 사이 새로 올라온 회사가 채워진다 —
    preliminary_target_term() 은 기존처럼 넓은 창(분기 시작~마감일) 전체에서 값을 준다.

둘 다 창 밖이면 None — 호출부는 DART를 부르지 않고 스킵한다. 반복 실행은
안전하다(automation/quarterly_financial_update.sh, scripts/pipeline/collect_preliminary_earnings.py
모두 회사별 idempotent upsert — 없으면 스킵, 있으면 덮어씀).

  .venv/bin/python automation/quarterly_term_window.py                        # 오늘, formal
  .venv/bin/python automation/quarterly_term_window.py --mode preliminary     # 오늘, preliminary
  .venv/bin/python automation/quarterly_term_window.py --mode formal 2026-05-20  # 특정 날짜(테스트용)
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

_DEADLINE_MMDD = {1: (5, 15), 2: (8, 15), 3: (11, 15), 4: (3, 31)}


def parse_term(term: str) -> tuple[int, int]:
    return int(term[:4]), int(term[-1])


def term_deadline(term: str) -> date:
    year, quarter = parse_term(term)
    mm, dd = _DEADLINE_MMDD[quarter]
    deadline_year = year + 1 if quarter == 4 else year  # 사업보고서(Q4)만 다음 해 3/31
    return date(deadline_year, mm, dd)


def preliminary_target_term(today: date) -> str | None:
    """분기 시작 ~ 마감일 전체 — 잠정실적은 이 구간에 흩어져서 올라온다."""
    y, m, d = today.year, today.month, today.day

    if m in (1, 2, 3):
        return f"{y - 1}Q4"
    if m == 4:
        return f"{y}Q1"
    if m == 5:
        return f"{y}Q1" if d <= 15 else None
    if m == 7:
        return f"{y}Q2"
    if m == 8:
        return f"{y}Q2" if d <= 15 else None
    if m == 10:
        return f"{y}Q3"
    if m == 11:
        return f"{y}Q3" if d <= 15 else None
    return None


def formal_target_term(today: date) -> str | None:
    """마감일 다음날(+1) 또는 마감일+8일(지각 제출 정리용)에만 값을 준다."""
    for q in (1, 2, 3, 4):
        for y in (today.year - 1, today.year):
            term = f"{y}Q{q}"
            deadline = term_deadline(term)
            if today in (deadline + timedelta(days=1), deadline + timedelta(days=8)):
                return term
    return None


def main() -> int:
    args = sys.argv[1:]
    mode = "formal"
    if "--mode" in args:
        i = args.index("--mode")
        mode = args[i + 1]
        del args[i : i + 2]

    today = date.fromisoformat(args[0]) if args else date.today()
    fn = preliminary_target_term if mode == "preliminary" else formal_target_term
    term = fn(today)

    if term is None:
        print("", end="")
        return 1
    print(term, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
