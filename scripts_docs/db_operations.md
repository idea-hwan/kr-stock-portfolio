# DB 사용법 (usage)

분기 원천·벨류에이션 스크립트를 **어떻게 쓰는지**를 **A / B / C** 로 나눈다. (스키마·경로·참조 관계는 [db.md](./db.md).)

- **A — DART 적재:** KRX 리스트·DART로 **분기별** 재무·배당·주식수 SQLite를 채운다. 아래 **A1 → A5**는 **A만** 해당한다.  
- **B — 수익 기준 벨류에이션:** **DART·공시 API를 호출하지 않고**, 로컬 **분기 DB**(SQLite)만 읽어 **TTM·PER** → `data/analytics/ttm_valuation.db`. **A의 연장 번호가 아니다.** 한 줄 요약은 아래 **「B — … 한 줄 요약」**, 실행 파일·명령은 **「B 상세」**(A 상세 바로 다음). 옵션 표·갭·쿼리는 [ttm_valuation.md](./ttm_valuation.md).  
- **C — 분배 기준 벨류에이션:** 배당·분배 정책 관점(배당수익률, DPS 추이 등). **B와 목적·데이터 레일이 다르다.** 상세는 **「C — 분배 기준 벨류에이션」 절** (통합 파이프라인·전용 문서는 필요 시 추가).

아래 Python 명령은 모두 **`scripts/pipeline/`** 아래 스크립트를 가리킨다.  
스키마·폴더 구조·명령 예시는 [db.md](./db.md)를 본다.  
재무 SQLite에서 **어떤 표(`sj_nm`)·계정(`account_id`)을 읽을지**는 적재 이후 분석 단계 정책이며, 상세는 [fs_resolution.md](./fs_resolution.md) 이다.

실행은 **`.venv/bin/python scripts/.../foo.py`** 처럼 인터프리터를 붙인다(실행 비트 없이 경로만 치면 `permission denied`). **A** 의 상위 N종목은 **`--top-n N`** (`update_quarter_dbs` / `range`). **B** 는 아래 한 줄 요약 + **B 상세**. **C** 는 해당 스크립트 도움말.

---

## A — DART 적재: 한 줄 요약 (A1 → A5)

**A1** **리스트** — 갱신 + `new_codes` diff (매번)  
**A2** **이번 분기** — `update_quarter_dbs.py` (매번) · **DART 키:** `stock_listing` **종목코드**로 `find_corp_code`가 안 되면 **같은 행 회사명(`Name`)**으로 재무·배당·주식수 조회 (`scripts/stock_db.py`, 별도 스텝 번호 아님)  
**A3** **이름 변경** — `rename_company_tables.py` (**예외**, 해당할 때만)  
**A4** **신규 백필** — `backfill_new_listing.py` (**예외**, 해당할 때만; **DART 키**는 A2와 동일 폴백)  
**A5** **오딧** — `audit_data_dbs.py` (매번, 마지막)

**A3·A4**는 “이번 분기 적재”가 끝난 뒤, 실제로 이름 변경·신규 코드가 있을 때만 수행한다. 둘 다 필요하면 **A3 → A4** 순.

---

## B — 수익 기준 벨류에이션: 한 줄 요약 (1 → 4)

1. **원천** — TTM에 쓸 분기 원천 SQLite가 있어야 한다. 경로·파일 규칙은 [db.md](./db.md) 「`populate_ttm_valuation` 이 읽는 분기 원천」. **B 스크립트는 DART를 부르지 않고 로컬만 읽는다.** 비었거나 없으면 원천 채우기는 **A2** 등([db.md](./db.md) 적재 절). **기본 종목 범위는 A2와 동일**(우선주·스팩·리츠·KONEX·KOSDAQ GLOBAL 등 제외, `stock_db.py` 단일 기준).  
2. **적재** — `populate_ttm_valuation.py` 로 `ttm_valuation.db` 채움.  
3. **조회** — `ttm_valuation_df.py` 로 터미널 표(적재와 별도 실행).  
4. **(선택) 확인** — `sqlite3` 로 배치·행 수 점검([ttm_valuation.md](./ttm_valuation.md) 쿼리 예시).  
5. **(선택) 성장 스크리닝** — 분기성장률·`1y_%`~`8y_%` (배치 시 `ttm_metric_growth.db`): [ttm_metric_growth.md](./ttm_metric_growth.md) · `.venv/bin/python scripts/screening/ttm_metric_growth.py` / `ttm_metric_growth_top_n.py`

**A의 A1 ~ A5와 번호·잡을 섞지 않는다.** 로직·정책을 바꿨으면 **재적재**.

**설명할 때:** B만 말할 땐 선행을 **「분기 SQLite가 디스크에 있다」**로만 말하면 된다. 그 파일을 **어떻게 채우는지**가 DART 적재 트랙(**A**, 특히 **A2**)이고, B 설명에 A를 꼭 끼워 넣지 않아도 된다.

---

## C — 분배 기준 벨류에이션

**주주 분배** 관점 — 배당 공시·배당 DB·(필요 시) 주가로 배당수익률·DPS 추이·성장 스크리닝 등을 본다. **B** 는 재무제표 기반 TTM·PER이므로 **C와 섞어 한 번에 해석하지 않는다.** 배당성향처럼 **EPS(재무)와 DPS(배당)를 조합**하는 지표는 두 DB 출처를 명시한다.

- **선행:** **A** 로 해당 종목·분기의 **배당**(`data/dividend`)·리스트가 갖춰져 있어야 한다. 재무까지 쓰는 지표면 재무 분기 DB도 필요하다.  
- **시계열·주가배수(프로토타입):** 배당 공시 누적 → 분기 증분 → 4Q TTM 주당배당, 액면 보정 후 **주가 ÷ TTM DPS** 및 **20일·4년 평균**(B의 PER와 같은 축). 시총 상위 1종목만:  
  `.venv/bin/python scripts/analysis/dividend_valuation_series.py --top-n 1`  
  종목 지정: `--company 삼성전자` · 주가 생략: `--no-price`  
- **레거시 스크립트:** 루트 `new_dividend_growth_stock.py`, `dividend_growth_stock.py` 등.

---

**A 상세 — 단계 A1 ~ A5**

## A1. 리스트·신규 코드

1. **KRX 상장 리스트 갱신**

   ```bash
   .venv/bin/python scripts/pipeline/update_stock_listing.py
   ```

   - 결과: `stock_data/stock_listing.csv` (백업: `stock_data/backups/`)

2. **`stock_data/new_codes_since_stock_csv.txt`**  
   `stock.csv` 대비 `stock_listing`에만 있는 코드로 다시 맞춘다.

3. **OPENDART** — `.env` 키, 당일·일 한도 확인

---

## A2. 이번 분기 전 종목 적재

리스트 기준으로 **해당 연·분기** `.db`를 채운다. 주기 작업의 **본선**이다.

```bash
.venv/bin/python scripts/pipeline/update_quarter_dbs.py <연도> <분기> [옵션]
```

- 타입만: `--types financial_statement` / `dividend` / `stocks` (여러 개 가능)
- 시총 상위만: `--top-n 30`
- 한 종목만: `--company 하나금융지주` (여러 번 지정 가능)
- 적재 전 리스트도 갱신: `--update-listing` (**A1** 과 겹치면 생략 가능)
- **여러 분기 한 번에:** `scripts/pipeline/update_quarter_dbs_range.py 2015Q1 2025Q4` … 동일하게 `--top-n` / `--company` 사용.
- **전 종목 적재 시 기본 제외:** 우선주(이름 끝 `우`·`우B`), 이름에 `스팩`·`리츠`·`펀드`·`신탁`, `Dept`에 `SPAC`, 시장 `KONEX`·`KOSDAQ GLOBAL`. 이 규칙을 끄는 옵션은 두지 않는다(항상 동일 유니버스).
- **적재와 분석(B·C 시총 순 등)은 같은 “허용 유니버스”**를 쓴다. 구현은 `scripts/stock_db.py` 의 `listing_pipeline_allowed_names()`·`listing_instrument_exclusion_mask()` 가 단일 기준(우선주·이름 스팩·리츠·펀드·신탁·Dept SPAC·**KONEX·KOSDAQ GLOBAL** 제외). `populate_ttm_valuation.py` 기본·`--company` 검증·`ttm_valuation_df` / `dividend_valuation_series` 의 `--top-n` 도 동일.

**DART 조회 키 (코드 → 이름):** `FS_DB` 의 재무(`finstate_all`)·배당(`report`)·주식총수(`report`)는 먼저 **정규화한 종목코드**로 `OpenDartReader.find_corp_code`를 쓰고, 없으면 **`stock_listing.csv` 의 `Name`**으로만 다시 시도한다(이름도 매칭 실패 시 기존처럼 코드 문자열로 호출). 로그에 `(DART: 종목코드 미매칭 → 회사명으로 … 조회)`가 뜨면 폴백이 동작한 것이다. **과거에 빈 테이블만 남은 분기는 이 로직 적용 후 해당 분기를 다시 돌려야 채워진다.**

[db.md](./db.md) 「2) 이번 분기 DB 적재」

---

## A3. 이름만 바뀐 종목 (예외)

같은 코드, 회사명만 다른 경우에만. **A2 다음**, 신규 백필보다 **앞서** 돌린다.  
`stock.csv`와 `stock_listing.csv`를 비교해 바뀐 쌍이 없으면 `No renames from listing diff.` 로 **바로 끝난다** (DB는 안 건드림).

```bash
.venv/bin/python scripts/pipeline/rename_company_tables.py --dry-run
.venv/bin/python scripts/pipeline/rename_company_tables.py
```

[db.md](./db.md) 「4) 같은 종목코드…」

---

## A4. 신규 종목 백필 (예외)

`new_codes_since_stock_csv.txt`에 코드가 있고, 과거 분기까지 채워야 할 때만.  
파일이 비었거나(또는 스팩만 있어서 전부 제외되면) `No pairs to backfill.` 로 **바로 끝난다**.  
**DART 키**는 **A2**와 같다(`finstate_data` / `dividend_data` / `stock_data`에 `name` 전달 → 코드 미매칭 시 회사명 폴백).

- 기본: **2023Q1 ~ 2025Q4**, 세 타입, 스팩 제외 (`--types` 생략 시 세 가지 모두)

```bash
.venv/bin/python scripts/pipeline/backfill_new_listing.py
```

장시간이면 로그:

```bash
mkdir -p logs
PYTHONUNBUFFERED=1 .venv/bin/python scripts/pipeline/backfill_new_listing.py >> logs/backfill_new_listing.log 2>&1 &
```

[db.md](./db.md) 「3) 신규 상장…」

---

## A5. 오딧 (전수 점검)

**A1·A2**는 끝난 뒤 **항상** 실행한다. **A3·A4**를 했으면 그 다음에 돌린다.

```bash
.venv/bin/python scripts/pipeline/audit_data_dbs.py
```

- 이번 분기만: `--start-term 2025Q4 --end-term 2025Q4` 등으로 구간 축소

옵션·출력 해석은 [db.md](./db.md) 「분기 DB 전수 점검 스크립트」.

### (선택) 표본·분석 스크립트

- 종목 몇 개 직접 테이블 확인
- `new_dividend_growth_stock.collect_data` 등 (`marcap` 필요한 스크립트는 환경 맞출 것)

---

**B 상세 — 단계 B1 ~ B4** (마지막 절은 선택)

## B1. (최초 1회) 분석 DB 스키마

`data/analytics/ttm_valuation.db` 가 없거나 테이블을 새로 만들 때만.

```bash
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --init-db
```

---

## B2. TTM·PER 적재 (`populate_ttm_valuation.py`)

결과: `data/analytics/ttm_valuation.db` 의 `ttm_valuation_series` 등.

- **`--term`**: 앵커 분기. **최신 공시 기준**이면 보통 가장 끝 분기(예: `2025Q4`), **과거 시점 기준**이면 그 분기(예: `2024Q1`)로 둔다. 시계열이 과거로 얼마나 길게 나가는지는 **원천에 해당 분기 `.db` 가 얼마나 있느냐**에 따른다.
- **종목 범위**: `--limit` 없음 = `stock_listing.csv` 기준 **전 종목**(스팩·우선주 제외 등 기본 필터 적용 후 전체, 부담 큼). `--limit N` = 시총 순 상위 N. `--company 이름` = 해당 Name 만(여러 번 지정 가능, 이때 **`--limit` 무시**).

프로젝트 루트에서 실행. `2025Q4`·`2024Q1`·`N`·종목명은 실제에 맞게 바꾼다.

```bash
# 최신 앵커 · 모든 종목 (--limit 생략, 부담 큼)
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2025Q4

# 최신 앵커 · 시총 상위 N
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2025Q4 --limit N

# 최신 앵커 · 특정 종목 (--company 는 여러 번 가능)
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2025Q4 --company 삼성전자

# 특정 앵커(과거 분기) · 모든 종목
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2024Q1

# 특정 앵커 · 시총 상위 N
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2024Q1 --limit N

# 특정 앵커 · 특정 종목
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2024Q1 --company 삼성전자
```

상장 리스트 갱신은 **A1** (`update_stock_listing.py`)에서 한다. 위가 **재무·TTM·주가·PER까지** 쓰는 통상 경로다. 그 밖의 옵션(`--market`, `--sleep`, 다중 `--company` 등)은 [ttm_valuation.md](./ttm_valuation.md) 표를 본다.

---

## B3. 터미널 조회 (`ttm_valuation_df.py`)

**적재와 별도**로 실행한다. DB 기본 경로는 스크립트 기본값(`data/analytics/ttm_valuation.db`).

- **한 종목**

  ```bash
  .venv/bin/python scripts/analysis/ttm_valuation_df.py --company 삼성전자
  ```

- **시총 상위 N종목** (`-n` / `--n` / `--top-n` 동일)

  ```bash
  .venv/bin/python scripts/analysis/ttm_valuation_df.py -n N
  ```

- **최근 분기만 잘라 보기**(예시)

  ```bash
  .venv/bin/python scripts/analysis/ttm_valuation_df.py --company 삼성전자 --tail 5
  ```

뷰·앵커·CSV 저장은 `--help` 와 [ttm_valuation.md](./ttm_valuation.md) 를 본다.

### (선택) B4. SQLite로 배치 확인

```bash
sqlite3 data/analytics/ttm_valuation.db "SELECT DISTINCT computed_at, logic_version FROM ttm_valuation_series ORDER BY computed_at DESC LIMIT 5;"
```

종목·앵커별 행 수·샘플 `SELECT` 는 [ttm_valuation.md](./ttm_valuation.md) 「한 종목·구간 백필 후 TTM」 절.

---

## 자주 쓰는 흐름

**A — DART 적재**

- **리스트 → 이번 분기 → (이름, 필요 시) → (신규 백필, 필요 시) → 오딧**  
- 오딧은 **이름 변경 여부를 검사하지 않는다** — 이름 이슈는 **A3** 에서 처리한다.

**B — 수익 기준 벨류에이션**

- **B 상세** 순서(최초 `ttm_valuation.db` 스키마 → `populate` 적재 → `ttm_valuation_df` 조회; 선택으로 SQLite 확인). 원천 경로는 [db.md](./db.md) 「`populate_ttm_valuation` 이 읽는 분기 원천」. **A1 ~ A5 전체를 끝낼 필요는 없고**, 해당 연·분기·종목의 원천 `.db` 가 없으면 적재 결과가 비거나 에러가 난다. 옵션·갭은 [ttm_valuation.md](./ttm_valuation.md).

**C — 분배 기준 벨류에이션**

- **A** 로 배당(및 필요 시 재무) 분기 DB를 먼저 갖춘 뒤, 배당·분배 스크립트를 돌린다. B와 **같은 잡에 묶을 필요 없음**.
