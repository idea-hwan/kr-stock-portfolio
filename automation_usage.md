# 자동화 스케줄러 사용법 (`automation/`)

로컬 macOS 터미널에 계속 띄워두는 방식의 foreground 스케줄러. launchd 같은
백그라운드 서비스가 아니라, 터미널 하나를 잡아두고 그 프로세스가 살아있는 동안만
동작한다. 세 트랙(데일리 가격 / 분기 재무 / 잠정실적) 전부 `automation/kr_stock_scheduler.py`
하나가 시간 체크만 하고, 실제 작업은 각 `.sh` 스크립트에 위임한다.

## 실행

```bash
caffeinate -i .venv/bin/python automation/kr_stock_scheduler.py
```

`caffeinate -i`는 이 프로세스가 살아있는 동안 macOS가 잠들지 않게 막는다. 터미널을
닫거나 Ctrl+C로 스케줄러를 끄면 그 뒤로는 아무 것도 실행되지 않는다 — launchd
상시 서비스가 아니므로 재부팅·터미널 종료 후엔 다시 띄워야 한다.

## 스케줄 (KST 기준)

| 트랙 | 시각 | 스크립트 | 비고 |
| --- | --- | --- | --- |
| 데일리 가격 | 매일 16:00 | `daily_update.sh` | 가격 → 팩터 패널 → PIT 버킷 → 대시보드 재생성 → 변경 있으면 자동 commit+push (`docs/index.html`, GitHub Pages 재배포) |
| 분기 재무(조건부) | 매일 09:00 체크 | `quarterly_financial_update.sh` | 마감일(5/15·8/15·11/15·3/31) **+1일 또는 +8일**에만 실제 실행, 그 외엔 즉시 스킵 |
| 잠정실적 | 매주 토요일 12:00 | `preliminary_earnings_update.sh` | 시각은 중요하지 않음(정식 공시 전 조기 반영이라 여유 있게) |

시각을 바꾸려면 `automation/kr_stock_scheduler.py` 상단의
`DAILY_HOUR`/`QUARTERLY_HOUR`/`PRELIMINARY_WEEKDAY`·`PRELIMINARY_HOUR` 등 상수를
수정한다.

### 왜 분기 재무 잡은 "매일 체크"인가

마감일이 해마다 다른 요일에 걸리기 때문에 특정 요일로 스케줄링할 수 없다. 그래서
매일 09:00에 `automation/quarterly_term_window.py`로 오늘 날짜만 확인하고, 트리거
날짜(마감+1일/+8일)가 아니면 DART 호출 없이 즉시 종료한다 — 1년 361일은 사실상
공짜 체크다. 실제 무거운 작업(A1 리스트 → A2 적재 → A5 오딧 → B2 TTM·PER)은 분기당
2번(마감+1일, 마감+8일)만 돈다.

## 로그

- `automation/logs/scheduler.log` — 스케줄러가 "언제 뭘 실행했는지"만 기록
- `automation/logs/YYYYMMDD_{daily,quarterly,preliminary}.log` — 각 잡의 상세 로그

**분기 재무 잡은 실행 빈도가 낮으니(분기당 2번) `*_quarterly.log`는 실행될 때마다
직접 열어서 확인하는 걸 권장한다.** 실패해도 스케줄러가 알림을 보내지는 않고
로그에 "실패 (exit N)"만 남는다.

## 신규 상장 종목 감지 (자동 감지, 백필은 수동)

`update_stock_listing.py`(A1)가 실행될 때마다 이전 `stock_listing.csv` 대비 새로
생긴 코드를 `stock_data/new_codes_since_stock_csv.txt`에 자동으로 append(dedup)한다.
`quarterly_financial_update.sh`가 A1 직후 이 파일이 비어있지 않으면 로그에

```
>>> 신규 상장 종목 대기 N개 (stock_data/new_codes_since_stock_csv.txt) — 필요하면 backfill_new_listing.py 직접 실행 (자동 실행 안 됨)
```

리마인더를 남긴다. **실제 백필 실행은 자동화하지 않는다** — 신규 상장은 첫
분기 데이터가 부실하거나(반기만 있음, 액면분할 직후 배수 왜곡 등) 이름이 비슷한
다른 종목과 오탐될 위험이 있어서, 이 파일을 사람이 보고 판단해서 직접 돌린다:

```bash
.venv/bin/python scripts/pipeline/backfill_new_listing.py
```

이미 백필된 종목은 `skip_existing` 기본값 때문에 재실행해도 API를 다시 안 부르므로,
파일에서 처리된 코드를 지우지 않고 그냥 둬도 안전하다(멱등).

## 알아두어야 할 제약

1. **분기 재무 잡 실패 시 뒷단계가 통째로 스킵된다** — `quarterly_financial_update.sh`는
   `set -euo pipefail`로 한 블록에서 A1→A5→B2를 순서대로 실행한다. A5(오딧)가
   비정상 종료하면 B2(TTM·PER 재계산)와 `stock_listing.csv`/`mcap_top_200.csv`
   git commit+push가 실행되지 않고 조용히 멈춘다. 로그에서 "실패"를 직접 확인해야
   안다.
2. **분기당 재시도 기회가 사실상 2번뿐** — 마감+1일/+8일 둘 다 실패하면(DART API
   장애 등) 다음 자동 트리거는 약 3개월 뒤 다음 분기 마감일이다. 그 사이엔
   `automation/quarterly_financial_update.sh <연도> <분기>`로 연·분기를 직접
   지정해서 수동 재실행해야 한다.
3. **foreground 프로세스** — 터미널 종료·맥 재부팅 시 스케줄러도 같이 죽는다.
   상시 서비스가 필요하면 launchd로 전환을 고려(현재는 의도적으로 터미널
   방식 선택).
