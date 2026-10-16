# AGENTS.md — AI 코딩 에이전트(Cursor 등)용 작업 안내

이 파일은 이 저장소에서 일하는 AI 에이전트가 **작업 전에 먼저 읽는 안내서**다.
사람용 개요는 [README.md](README.md), 스크립트 색인은 [usage.md](usage.md)에 있다.
여기에는 "이 프로젝트에서 무엇을 하면 안 되고, 무엇을 어떤 순서로 해야 하는지"를 적는다.

사용자는 한국어로 대화한다. 답변·커밋 메시지·문서도 한국어로 쓴다.

---

## 1. 이 프로젝트가 하는 일 (한 문단 요약)

한국 상장사의 DART 재무제표를 분기별 SQLite로 쌓고(`data/`), 그걸로 TTM·PER·성장률 지표를
계산해, **시총 상위 200 종목을 성장/밸류 버킷으로 나누고 매수·매도 신호를 붙인 대시보드**
(`docs/index.html`, GitHub Pages로 공개)를 매일 자동으로 갱신한다. 매주 화요일에는 그 신호를
사람+AI가 검증해 **주간 신호 리포트**(`docs/signal_reports/YYYY-MM-DD.md`)를 쓴다.

```
DART API ──(분기, 자동)──▶ data/financial_statement|dividend|stocks/*.db   ← 원천
                              │
                              ▼
               data/analytics/ttm_valuation.db, ttm_metric_growth.db       ← 지표
                              │
가격(FinanceDataReader, 매일) ─┤
                              ▼
     mcap200_factor_panel.csv → pit_buckets.db → docs/index.html           ← 대시보드
                                                       │
                                     (매주 화, 수동) ──▶ docs/signal_reports/*.md
```

## 2. 실행 환경

- macOS, Python 3.10, 가상환경 `.venv/`
- **모든 명령은 프로젝트 루트에서, `.venv/bin/python 경로/파일.py` 형태로 실행한다.**
  `python`이나 `python3`를 그냥 쓰지 말 것(패키지가 없는 시스템 파이썬이 잡힌다).
- API 키는 `.env`의 `DART_API_KEY` 하나뿐이다. `scripts/config.py`가 자동으로 읽는다.
- 옵션은 각 스크립트의 `--help`로 확인한다.

## 3. 저장소에 없는 것 — 매우 중요

`.gitignore` 때문에 다음은 git에 없고, 이 컴퓨터에만 있다.

| 경로 | 내용 | 없어지면 |
|---|---|---|
| `data/` (약 6GB) | 2015년~ 분기 원천 DB + 분석 DB | DART로 재수집에 **며칠** 걸림. 절대 지우지 말 것 |
| `.env` | DART API 키 | 데이터 수집 불가 |
| `automation/logs/` | 자동화 실행 로그, `scheduler_state.json` | 로그만 사라짐 |
| `docs_cache/` | DART 고유번호 캐시 | 자동 재생성 |

따라서:
- `data/` 아래 파일을 **삭제·이동·덮어쓰는 명령은 사용자에게 먼저 확인**받는다.
- `data/`, `.env`, `*.db`를 git에 추가하지 않는다.
- "파일이 없다" 오류가 나면 코드를 고치기 전에 `data/`가 제대로 복사됐는지부터 의심한다
  (README의 "새 맥으로 옮길 때" 참고).

## 4. 자동화 — 이미 돌고 있는 것을 건드리지 말 것

터미널 하나에 스케줄러가 떠 있다:

```bash
caffeinate -i .venv/bin/python automation/kr_stock_scheduler.py
```

| 잡 | 언제 | 무엇을 | git |
|---|---|---|---|
| `automation/daily_update.sh` | 매일 16:00 | 가격 → 패널 → PIT → 대시보드 | `docs/index.html` 자동 commit+**push** |
| `automation/quarterly_financial_update.sh` | 공시 마감일+1일, +8일 09:00 | DART 분기 재무 적재 → TTM·성장률 재계산 | `stock_data/stock_listing.csv`, `mcap_top_200.csv` 자동 commit+**push** |
| `automation/preliminary_earnings_update.sh` | 매주 토 12:00 | 잠정실적 수집 | 없음 |

잠자기나 재시작으로 시각을 놓치면 깨어난 뒤 자동으로 따라잡는다. 상세 내용은 [automation_usage.md](automation_usage.md)에 있다.

에이전트가 지킬 것:
1. **스케줄러가 main에 직접 push한다.** 그래서 커밋하기 전에 항상 `git pull --rebase`부터 한다.
   push가 거절되면 force push 하지 말고 pull 후 다시 시도한다.
2. 위 세 스크립트를 **사용자 요청 없이 직접 실행하지 않는다.** 순서와 타이밍이 정해져 있다.
   유일한 예외는 주간 리포트 절차에서 잠정실적 재수집이다(6절 참고).
3. 스케줄러를 두 대의 컴퓨터에서 동시에 띄우지 않는다. 둘이 같은 파일을 push하다 충돌한다.
4. 자동화 결과를 확인할 때는 다음 로그를 본다.
   - `automation/logs/scheduler.log`: 언제 무엇이 실행됐는지
   - `automation/logs/YYYYMMDD_{daily,quarterly,preliminary}.log`: 각 실행의 상세 내용
   - 실패해도 알림이 없고 로그에 `실패 (exit N)`만 남는다.

## 5. 비싸거나 위험한 명령

- `update_quarter_dbs.py` / `update_quarter_dbs_range.py` / `--full` 옵션은 DART를 종목마다
  호출하고(종목당 약 2초), 전 종목이면 **몇 시간** 걸린다. DART에는 하루 호출 한도가 있다.
  테스트할 때는 `--top-n 10`처럼 작게 시작하고, 큰 범위는 사용자 확인 후 실행한다.
- `rename_company_tables.py`는 SQLite 테이블명을 바꾼다. 반드시 `--dry-run`을 먼저 실행한다.
- `stock_data/stock.csv`는 오래돼 보이지만 `rename_company_tables.py`의 기준 스냅샷이다. 지우지 않는다.
- 재무 계정 매핑(`scripts/analysis/fs_metrics.py`, [scripts_docs/fs_resolution.md](scripts_docs/fs_resolution.md))을
  바꾸면 TTM 전체를 재적재해야 한다. 바꾸기 전에 사용자와 상의한다.

## 6. 사람이 요청할 때만 하는 수동 작업

### 주간 매수·매도 신호 리포트 (매주 화요일)

사용자가 "주간 리포트 써줘"라고 하면 **[automation/prompts/weekly_signal_report_prompt.md](automation/prompts/weekly_signal_report_prompt.md)를
처음부터 끝까지 읽고 그 절차를 그대로 따른다.** 웹 검색으로 뉴스를 검증하는 단계가 있다.

절차 문서에 더해, 사용자가 명시적으로 요구한 작성 원칙이 있다.
- **분량이 아니라 논리를 늘린다.** 제외·재검토·고위험 종목도 한 줄로 사실만 나열하고 끝내지 않는다.
  다음 흐름을 2~3문장으로 풀어쓴다.
  ① 신호가 뜬 근거 → ② 리스크나 반박 근거가 그 신호를 왜 흔드는지(또는 뒷받침하는지) → ③ 그래서 이 분류가 된 이유
- 새로운 사실을 더 조사하라는 뜻이 아니다. 이미 확인한 사실 사이의 인과관계를 명시하라는 뜻이다.
- 최종 후보 항목은 2~4문장으로 쓴다.
- **커밋·push 전에 반드시 사용자에게 보여주고 검토받는다.**
  결과물은 `docs/signal_reports/<날짜>.md`와 재생성한 `docs/index.html` 두 파일이다.

### 신규 상장 종목 백필

`stock_data/new_codes_since_stock_csv.txt`에 코드가 쌓여 있으면 분기 로그에 리마인더가 남는다.
상장 직후 데이터는 부실할 수 있어서 자동으로 백필하지 않는다. 사용자가 요청하면 실행한다.

```bash
.venv/bin/python scripts/pipeline/backfill_new_listing.py
```

같은 코드를 다시 실행해도 안전하다(이미 있는 데이터는 건너뜀).

### 분기 재무 수동 재실행

자동 실행이 실패했을 때만 사용자 확인 후 실행한다.

```bash
automation/quarterly_financial_update.sh 2026 3
```

## 7. 코드 작성 규칙

- 주변 코드 스타일을 따른다. 주석과 docstring은 한국어로 쓰고, "왜 이렇게 했는지"를 날짜·사례와 함께 남기는 스타일이다.
- 경로는 `Path(__file__)` 기준으로 프로젝트 루트를 잡는다. `/Users/...` 같은 절대경로를 하드코딩하지 않는다.
- 새 스크립트는 기능에 맞는 폴더에 둔다(`scripts/pipeline`, `analysis`, `screening`, `simulate`, `snapshot_export`).
  그리고 [usage.md](usage.md) 색인에 한 줄을 추가한다.
- 패키지를 추가하면 `requirements.txt`에 버전을 고정해서 적는다.
- 신호 공식이나 버킷 기준을 바꾸면 [docs/large_growth_selection_strategy.md](docs/large_growth_selection_strategy.md),
  [docs/large_value_selection_strategy.md](docs/large_value_selection_strategy.md),
  [scripts_docs/stock_classification.md](scripts_docs/stock_classification.md)도 함께 갱신한다.

## 8. 문서 색인

| 알고 싶은 것 | 문서 |
|---|---|
| 전체 파이프라인 개요, 새 맥 세팅 | [README.md](README.md) |
| 스크립트별 한 줄 설명 | [usage.md](usage.md) |
| 자동화 스케줄·로그·제약 | [automation_usage.md](automation_usage.md) |
| DB 경로·스키마 | [scripts_docs/db.md](scripts_docs/db.md) |
| 적재 절차 A/B/C | [scripts_docs/db_operations.md](scripts_docs/db_operations.md) |
| 지표 정의 | [financial_metrics.md](financial_metrics.md) |
| 버킷 분류 규칙 | [scripts_docs/stock_classification.md](scripts_docs/stock_classification.md) |
| 신호 공식·백테스트 | `docs/large_*_selection_strategy.md` |
| 진행 상황·할 일 | [TODO.md](TODO.md) |
