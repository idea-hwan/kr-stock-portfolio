# DB 운영 가이드

## 개요

이 프로젝트는 분기별 DB를 `data/` 아래에서 관리합니다.

**코드 위치:** 적재·점검 CLI는 `scripts/pipeline/` 이고, DB 접근·설정은 `scripts/stock_db.py`, `scripts/config.py` 이다. 분석용 코드는 `scripts/analysis/` 에 둘 예정이다.

**A — DART 적재**(분기 DB, **A1 ~ A5**), **B — 수익 기준 벨류에이션**(TTM·PER, `ttm_valuation.db`), **C — 분배 기준 벨류에이션**(배당·분배 스크립트)의 **사용법(usage)** 은 [db_operations.md](./db_operations.md)에서 나누어 설명한다. B 상세는 [ttm_valuation.md](./ttm_valuation.md). **TTM DB 기반 성장 스크리닝**(분기성장률·`1y_%`~`8y_%`등)은 [ttm_metric_growth.md](./ttm_metric_growth.md) ·`scripts/screening/ttm_metric_growth*.py`. **A1 ~ A5 뒤에 B·C를 6·7단계처럼 이어 붙이지 않는다.**  
**재무제표에서 어떤 표·계정을 읽을지**(연결/포괄손익, 개정 태그 등)는 [fs_resolution.md](./fs_resolution.md)를 본다.

- `data/financial_statement`: 재무제표 DB
- `data/dividend`: 배당 DB
- `data/stocks`: 주식수/주식변동 DB

각 분기는 SQLite 파일 1개로 저장됩니다.

- 형식: `<연도>Q<분기>.db` (예: `2025Q4.db`)

## `populate_ttm_valuation` 이 읽는 분기 원천

`scripts/pipeline/populate_ttm_valuation.py` 는 **공시 API를 부르지 않고** 아래만 읽는다. TTM 윈도에 쓰는 **각 연·분기**에 대해 세 디렉터리에 **같은 파일명**(`YYYYQX.db`)이 있어야 하고, 종목 테이블은 `stock_listing.csv` 의 **Name** 과 동일한 이름이다.


| 종류       | 경로                                     |
| -------- | -------------------------------------- |
| 재무       | `data/financial_statement/<YYYY>QX.db` |
| 배당       | `data/dividend/<YYYY>QX.db`            |
| 주식수·변동   | `data/stocks/<YYYY>QX.db`              |
| 시총 순 종목명 | `stock_data/stock_listing.csv`         |


이 파일을 **처음 채우거나 갱신**하는 절차는 [db_operations.md](./db_operations.md) **A2** 및 아래 「2) 이번 분기 DB 적재」.

## 디렉토리 구조

```text
data/
  financial_statement/
    2015Q4.db
    ...
    2025Q4.db
  dividend/
    2015Q4.db
    ...
    2025Q4.db
  stocks/
    2015Q4.db
    ...
    2025Q4.db
```

## 테이블 구조

각 DB에는 회사별 테이블이 다수 존재하며, 테이블명은 회사명(예: `삼성전자`)입니다.

### `dividend` DB 주요 컬럼

- `rcept_no`: DART 접수번호
- `corp_name`: 회사명
- `se`: 항목명 (예: `주당 현금배당금(원)`)
- `thstrm`, `frmtrm`, `lwfr`: 당기/전기/전전기 값
- `stlm_dt`: 결산일

### `financial_statement` DB 주요 컬럼

- `rcept_no`, `reprt_code`, `bsns_year`
- `sj_nm`: 재무제표 구분. DART 그대로라 **회사마다 조합이 다름** (예: `손익계산서`만, `포괄손익계산서`만, `연결`* 동시 등). 지표 추출 시 폴백 순서는 [fs_resolution.md](./fs_resolution.md) §2.
- `account_id`, `account_nm` — XBRL 태그·개정에 따라 동일 경제적 의미가 다른 id에 실릴 수 있음. 매핑은 `scripts/analysis/fs_metrics.py` 의 `SPECS` + [fs_resolution.md](./fs_resolution.md) §3.
- `thstrm_amount`, `frmtrm_amount`, `bfefrmtrm_amount`

### `stocks` DB 주요 컬럼

- `se`: 행 구분 (보통주/우선주/합계/비고)
- `isu_stock_totqy`, `istc_totqy`: 발행주식 관련 수량
- `now_to_dcrs_stock_totqy`, `redc`, `profit_incnr`, `rdmstk_repy`
- `tesstk_co`, `distb_stock_co`, `stlm_dt`

## 스톡 리스트 소스

`stock_data/stock_listing.csv`는 DB 적재 루프의 기준 파일입니다.

- 주기적으로 최신화 권장 (최소 월 1회, 권장: 분기 적재 전 1회)
- 갱신 스크립트: `scripts/pipeline/update_stock_listing.py`
- 실행 시 백업 파일 자동 생성: `stock_data/backups/`

### 적재·평가 대상 종목 선정

**기준 파일**은 위 `stock_listing.csv`이고, **시총 순 상위 N**을 쓸 때는 `Marcap` 컬럼 기준 내림차순(동일 이름은 큰 쪽 한 행)으로 `stock_db.py`가 정렬한 순서를 따른다. **DART 분기 적재(A2)**와 **`populate_ttm_valuation` 등 수익 기준 벨류(B)**는 기본으로 **같은 “허용 유니버스”**에서 종목을 고른다(우선주·이름/부서 기준 스팩·리츠·펀드·신탁, 시장 `KONEX`·`KOSDAQ GLOBAL` 제외 등). 구현의 단일 기준은 `scripts/stock_db.py`의 `listing_pipeline_allowed_names()`·`listing_instrument_exclusion_mask()`이다. **전체가 아니라 시총 상위 N만** 돌릴 때는 A에서 `--top-n`, B에서 `--limit`(또는 조회 스크립트의 `-n`)으로 그 순서의 앞쪽만 자른다. **종목을 직접 지정**하는 `--company` 등은 [db_operations.md](./db_operations.md) **A2**·**B 한 줄 요약**·**B2**에 정리되어 있다.

## 갱신/적재 절차

### 권장 실행 순서 (A1 → A5)

[db_operations.md](./db_operations.md) **A 상세** 와 같은 단계 이름이다.  
본문 아래 `1)~4)`는 **기능별 목차** 번호이고, **실제로 돌리는 순서**는 아래 표와 같다.  
**A3·A4**는 매번 할 일이 아니라 **이름 변경·신규 상장이 있을 때만** 하는 예외 처리다.


| 단계     | 할 일                                     | 비고            | 본문 목차(참고)             |
| ------ | --------------------------------------- | ------------- | --------------------- |
| **A1** | 리스트 갱신·신규 코드 diff                       | 매번            | 아래 `1)`               |
| **A2** | 이번 분기 전 종목 적재 (`update_quarter_dbs.py`) | 매번            | 아래 `2)`               |
| **A3** | 이름만 바뀐 종목 → `rename_company_tables.py`  | **예외** (해당 시) | 아래 `4)`               |
| **A4** | 신규 코드 백필                                | **예외** (해당 시) | 아래 `3)`               |
| **A5** | 전수 점검 `audit_data_dbs.py`               | 매번 (마지막)      | 아래 「분기 DB 전수 점검 스크립트」 |


**A3**와 **A4**가 **둘 다** 필요하면 **이름 통일(A3) → 신규 백필(A4)** 순이 맞다.

**번호 주의:** 본문 목차 `3)`·`4)`는 **나열 순서**(백필 → 이름)이고, **운영 순서 A3·A4**와 **뒤바뀐다**. 돌릴 때는 위 표만 보면 된다 (운영 A3 = 본문 `4)`, 운영 A4 = 본문 `3)`).

실행 파일·명령 블록은 [db_operations.md](./db_operations.md) **A 상세 — A1 ~ A5** 가 본문이다.

### 1) 스톡 리스트만 갱신

```bash
.venv/bin/python scripts/pipeline/update_stock_listing.py
```

### 2) 이번 분기 DB 적재 (재무 / 배당 / 주식)

`stock_listing.csv`를 기준으로 **해당 연·분기** `.db`를 만든다.  
리스트 갱신은 **기본 포함하지 않는다**. 필요할 때만 `--update-listing`을 붙인다.

**프로젝트 루트**에서:

```bash
.venv/bin/python scripts/pipeline/update_quarter_dbs.py <연도> <분기> [옵션]
```


| 하고 싶은 일            | 예시                                                                                           |
| ------------------ | -------------------------------------------------------------------------------------------- |
| **재무만**            | `.venv/bin/python scripts/pipeline/update_quarter_dbs.py 2025 4 --types financial_statement` |
| **배당만**            | `... --types dividend`                                                                       |
| **주식수만**           | `... --types stocks`                                                                         |
| **세 가지 한 번에** (기본) | `.venv/bin/python scripts/pipeline/update_quarter_dbs.py 2025 4`                             |
| 적재 **전**에 리스트도 갱신  | 끝에 `--update-listing` 추가                                                                     |


타입을 여러 개 고르면 항상 **재무 → 배당 → 주식** 순으로 실행된다.

### 3) 신규 상장 등 리스트에만 있는 종목 백필

`stock.csv` 대비 `stock_listing.csv`에만 있는 코드 목록은 `stock_data/new_codes_since_stock_csv.txt`에 둡니다.  
전체 분기를 다시 돌리지 않고, **해당 코드만** 각 분기 DB에 채웁니다.

- **기본 구간:** `--start-term` / `--end-term` 생략 시 **2023Q1 ~ 2025Q4**(약 3년·신규 종목에 맞춤). 더 긴 과거가 필요하면 `--start-term 2015Q4` 등으로 지정.
- **스팩 제외:** 회사명·부서 기준 스팩은 `stock_db` 필터와 동일하게 백필 대상에서 제외된다.
- 이미 같은 회사명 테이블이 있으면 기본적으로 **API 호출 생략**(`--no-skip-existing`로 덮어쓰기 가능)
- DB는 항상 프로젝트 `**data/`** 아래 (`financial_statement`, `dividend`, `stocks`)를 사용한다.

```bash
.venv/bin/python scripts/pipeline/backfill_new_listing.py \
  --types financial_statement dividend stocks
```

과거 구간을 넓히는 예:

```bash
.venv/bin/python scripts/pipeline/backfill_new_listing.py \
  --start-term 2023Q1 \
  --end-term 2026Q1 \
  --types financial_statement dividend stocks
```

### 4) 같은 종목코드, 회사명만 바뀐 경우 (테이블명 통일)

`stock_data/stock.csv`(과거 스냅샷)와 `stock_data/stock_listing.csv`(현재)를 같은 `Code`로 조인해  
`Name`이 다른 쌍을 찾아, 각 분기 DB 안의 **테이블명을 `ALTER TABLE ... RENAME`으로 현재명으로 맞춥니다.**

- 변경 목록 CSV: `stock_data/company_name_renames.csv` (자동 생성)
- 3번·4번을 같이 돌릴 때: **이름 통일(rename) → 신규 코드 백필**
- 먼저 `--dry-run`으로 확인 후, 문제 없으면 같은 명령에서 `--dry-run` 제거

```bash
.venv/bin/python scripts/pipeline/rename_company_tables.py --dry-run
.venv/bin/python scripts/pipeline/rename_company_tables.py
```

## 환경 변수

프로젝트 루트에 `.env` 파일을 생성합니다.

```env
DART_API_KEY=your_dart_api_key_here
```

코드는 `scripts/config.py`를 통해 해당 값을 읽습니다.

## 참고 / 데이터 특성

- `stocks` DB의 `2015Q4 ~ 2017Q4`는 원본도 빈 DB입니다.
- 복사 오류가 아니라 원천 데이터 특성입니다.
- `2018Q1`부터 실제 데이터가 채워집니다.
- DB 파일 자체는 원본 데이터로 보고, 스키마 변경은 지양합니다.
- 대용량 작업 전에는 `data/`를 다른 경로에 통째로 복사해 두는 것을 권장한다.

## 빠른 점검 명령어

### 폴더별 DB 파일 개수 확인

```bash
ls data/financial_statement/*.db | wc -l
ls data/dividend/*.db | wc -l
ls data/stocks/*.db | wc -l
```

### 특정 DB의 테이블 수 확인

```bash
sqlite3 data/stocks/2025Q4.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table';"
```

### 분기 DB 전수 점검 스크립트

**이번 분기 적재(2번)를 끝낸 뒤** 기본으로 돌리고, 예외 3·4를 했으면 **그 다음**에 한 번 더 돌리면 된다. 파일 누락·빈 분기·세 종류 간 대략적 균형을 빠르게 확인한다.

```bash
.venv/bin/python scripts/pipeline/audit_data_dbs.py \
  --start-term 2015Q4 \
  --end-term 2026Q1 
```

- 대상: 프로젝트 `**data/**`
- 기본 구간: `2015Q4` ~ `2025Q4`
- 다른 구간만 보려면: `--start-term 2024Q1 --end-term 2025Q4`
- 세 DB 간 `nonempty` 테이블 수 차이 출력 임계값: `--cross-diff 200` (기본). 로그를 줄이려면 `500` 등으로 올린다.

`stocks`의 `2015Q4~2017Q4`는 원천상 거의 비어 있을 수 있고, 재무는 배당·주식수보다 빈 테이블이 많은 것이 흔하다. 스크립트 마지막에 `OK`가 나와도 위 특성은 정상 범위로 본다.