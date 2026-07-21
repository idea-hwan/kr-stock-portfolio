# stock-portfolio

DART·KRX 상장 리스트를 기준으로 **분기별 원천 SQLite**를 쌓고, 이를 읽어 **TTM·PER·성장 지표 DB**를 만든 뒤, **버킷별 분류 스냅샷 CSV**를 뽑는 데이터 파이프라인입니다.

모든 명령은 **프로젝트 루트**에서 실행합니다. Python은 `**.venv/bin/python scripts/.../foo.py`** 형태를 쓰면 됩니다(실행 비트 없이 `foo.py`만 치면 `permission denied`가 날 수 있음).

---

## 사전 준비

- 가상환경: `requirements.txt` 기준으로 `.venv` 구성
- **Open DART API 키**: `.env` (예시는 `.env.example`). **분기 원천 적재(A)** 에서만 API를 부릅니다.
- 스키마·폴더 구조: [scripts_docs/db.md](scripts_docs/db.md)

---

## 1. 분기 DB 적재 (DART → SQLite)

`data/financial_statement/`, `data/dividend/`, `data/stocks/` 아래 **연·분기별 `.db`** 를 채우는 단계입니다. 문서에서는 **A (A1~A5)** 로 묶습니다.


| 단계  | 내용                                                                                                |
| --- | ------------------------------------------------------------------------------------------------- |
| A1  | KRX 리스트 갱신 → `stock_data/stock_listing.csv` (`update_stock_listing.py`)                           |
| A2  | 해당 분기 적재 (`update_quarter_dbs.py` 또는 구간 일괄 `update_quarter_dbs_range.py`)                         |
| A3  | (예외) 개명만 바뀐 종목 → 테이블명 정리 (`rename_company_tables.py`)                                             |
| A4  | (예외) 신규 상장 코드 과거 분기 백필 (`backfill_new_listing.py`, 입력 `stock_data/new_codes_since_stock_csv.txt`) |
| A5  | 점검 (`audit_data_dbs.py`)                                                                          |


**상세 순서·옵션·주의:** [scripts_docs/db_operations.md](scripts_docs/db_operations.md)

---

## 2. 밸류에이션·지표 DB (로컬 분기 DB만 읽어 다시 적재)

DART를 다시 호출하지 않고, **이미 있는 분기 SQLite**와 (필요 시) 시세로 분석용 DB를 만듭니다. 문서의 **B** 트랙에 해당합니다.

### 2a. TTM·주당·PER → `data/analytics/ttm_valuation.db`

```bash
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --init-db   # 최초 스키마만
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2026Q1 --limit 500
```

**상세:** [scripts_docs/ttm_valuation.md](scripts_docs/ttm_valuation.md) · 지표 정의: [financial_metrics.md](financial_metrics.md)

### 2b. 성장률 지표 → `data/analytics/ttm_metric_growth.db`

`ttm_valuation.db` 시계열을 읽어 기하 누적 성장률 등을 계산해 **별도 DB에 적재**합니다. **버킷 스냅샷 CSV**의 성장률 열과 대형·중소형 성장 조건에 쓰입니다.

```bash
.venv/bin/python scripts/screening/ttm_metric_growth_top_n.py --top-n 2500
```

단일 종목 확인만 할 때는 `ttm_metric_growth.py` / `ttm_metric_growth_lookup.py` ([scripts_docs/ttm_metric_growth.md](scripts_docs/ttm_metric_growth.md)).

---

## 3. 분류 → 버킷별 스냅샷 CSV

규칙·버킷 정의: [scripts_docs/stock_classification.md](scripts_docs/stock_classification.md)

**전제 (리밸런스·분기 확정 직전 스냅샷 권장):**

- 대형/중소 구분: `stock_listing.csv` 갱신 후 `stock_data/mcap_top_200.csv`  
`export_mcap_top_200.py`
- 대형 경기순환 유니버스: `stock_data/cyclical_manual_universe.txt`

**산출:** `data/analytics/cyclical_stock.csv`, `large_value_stock.csv`, `large_growth_stock.csv` — 동일 스키마, `export_bucket_stock_csv.py` 가 유니버스만 갈라 `stock_snapshot_core`로 합칩니다.

```bash
.venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket all
```

단일 종목 터미널 확인: `scripts/snapshot_export/cyclical_snapshot_terminal.py` (전체 CSV는 위 `export_bucket_stock_csv`만 사용). 스크립트 색인: [usdge.md](usdge.md).

---

## 그 밖의 레일

- **배당·분배 관점(C)** 은 B(재무 TTM·PER)와 목적이 다릅니다. 절차는 [scripts_docs/db_operations.md](scripts_docs/db_operations.md) 「C — 분배 기준 벨류에이션」.
- **스크립트 전체 목록·한 줄 설명:** [usdge.md](usdge.md)

---

## 문서 색인


| 문서                                                           | 내용                               |
| ------------------------------------------------------------ | -------------------------------- |
| [scripts_docs/db_operations.md](scripts_docs/db_operations.md)               | A/B/C 사용법, 명령 예시                 |
| [scripts_docs/db.md](scripts_docs/db.md)                                     | 경로·스키마·참조 관계                     |
| [scripts_docs/ttm_valuation.md](scripts_docs/ttm_valuation.md)               | `populate_ttm_valuation` 옵션·갭 점검 |
| [scripts_docs/ttm_metric_growth.md](scripts_docs/ttm_metric_growth.md)       | 성장률 DB·컬럼                        |
| [scripts_docs/stock_classification.md](scripts_docs/stock_classification.md) | 버킷 조건·스냅샷 열                      |
| [scripts_docs/fs_resolution.md](scripts_docs/fs_resolution.md)               | 재무 표·계정 매핑 (변경 시 TTM 재적재)        |


