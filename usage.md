# 실행 스크립트 색인

프로젝트 **루트**에서 실행한다. Python은 `.venv/bin/python` 을 가정한다. 스크립트들이 프로젝트 루트를 `sys.path`에 넣는 경우가 많아 별도 `PYTHONPATH`는 보통 불필요하다.

**옵션 전체**는 각 파일에 `--help` 로 확인한다.

```bash
.venv/bin/python scripts/pipeline/update_stock_listing.py --help
```

---

## `scripts/pipeline/` — 데이터 적재·갱신·점검

| 스크립트 | 하는 일 | 예시 |
|----------|---------|------|
| `update_stock_listing.py` | KRX 상장 리스트 → `stock_data/stock_listing.csv` (인자 없음) | `.venv/bin/python scripts/pipeline/update_stock_listing.py` |
| `export_mcap_top_200.py` | 시총 상위 N → `stock_data/mcap_top_200.csv` | `.venv/bin/python scripts/pipeline/export_mcap_top_200.py` |
| `update_quarter_dbs.py` | 지정 연·분기 재무·배당·주식 DB 적재 | `.venv/bin/python scripts/pipeline/update_quarter_dbs.py 2025 4 --top-n 10` |
| `update_quarter_dbs_range.py` | 구간 전 분기에 위와 동일 적재 | `.venv/bin/python scripts/pipeline/update_quarter_dbs_range.py 2015Q1 2025Q4 --top-n 10` |
| `backfill_new_listing.py` | 신규 상장 코드만 기존 분기 DB에 백필 | `.venv/bin/python scripts/pipeline/backfill_new_listing.py` |
| `dart_source_screen.py` | DART API 직접 호출·행 수 스크리닝 (한도 주의) | `.venv/bin/python scripts/pipeline/dart_source_screen.py 2024Q1 2025Q4 --company LG에너지솔루션 --types financial_statement` |
| `populate_ttm_valuation.py` | TTM·PER 시계열 → `data/analytics/ttm_valuation.db` | `.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --init-db` / `... --term 2025Q4 --limit 10` |
| `rename_company_tables.py` | 리스트 개명에 맞춰 SQLite 테이블명 변경 | `.venv/bin/python scripts/pipeline/rename_company_tables.py --dry-run` |
| `audit_data_dbs.py` | 분기별 `financial_statement`·`dividend`·`stocks` DB 점검 | `.venv/bin/python scripts/pipeline/audit_data_dbs.py` |

상세 순서·주의: `scripts_docs/db_operations.md`, `scripts_docs/ttm_valuation.md`, `scripts_docs/stock_classification.md`.

---

## `scripts/screening/` — TTM 성장률 DB

| 스크립트 | 하는 일 | 예시 |
|----------|---------|------|
| `ttm_metric_growth.py` | 단일 종목 성장률 표 출력 (DB 적재 아님) | `.venv/bin/python scripts/screening/ttm_metric_growth.py --company 삼성전자` |
| `ttm_metric_growth_lookup.py` | `ttm_metric_growth.db` 에서 조회·배치 목록 | `.venv/bin/python scripts/screening/ttm_metric_growth_lookup.py --company 삼성전자` / `--list-batches` |
| `ttm_metric_growth_top_n.py` | 시총 상위 N종 일괄 계산 → `ttm_metric_growth.db` | `.venv/bin/python scripts/screening/ttm_metric_growth_top_n.py --top-n 2500` |

규칙·컬럼: `scripts_docs/ttm_metric_growth.md`.

---

## `scripts/analysis/` — 조회·단일 종목 분석·스크리닝 스모크

| 스크립트 | 하는 일 | 예시 |
|----------|---------|------|
| `ttm_valuation_df.py` | `ttm_valuation.db` 종목별 조회·CSV | `.venv/bin/python scripts/analysis/ttm_valuation_df.py --company 삼성전자` |
| `per_share_roll4.py` | 주당 이익·CFO·Capex TTM (단일 또는 시계열) | `.venv/bin/python scripts/analysis/per_share_roll4.py --company 삼성전자 --term 2025Q4` |
| `fs_metrics.py` | 분기 재무 DB에서 지표 추출·프로브 | `.venv/bin/python scripts/analysis/fs_metrics.py --company 삼성전자 --term 2025Q4` |
| `dividend_valuation_series.py` | 배당 TTM·주가배수(pdps) 시계열 | `.venv/bin/python scripts/analysis/dividend_valuation_series.py --company 삼성전자` |
| `audit_ttm_pl_cf_gaps.py` | TTM DB 손익·CF 결측 불일치 점검 | `.venv/bin/python scripts/analysis/audit_ttm_pl_cf_gaps.py --anchor-term 2025Q4` |
| `local_source_teeth.py` | 로컬 3종 DB 이빨(불완전 적재) TSV 출력 | `.venv/bin/python scripts/analysis/local_source_teeth.py --company-names-file path/to/names.txt -o out.tsv` |
| `large_asset_lens_snapshot.py` | 대형 밸류 렌즈(싸다·1y 성장) | `.venv/bin/python scripts/analysis/large_asset_lens_snapshot.py --company 현대차` |
| `screen_large_asset_mcap200.py` | 문서 3.2절 대형 밸류주 1차 스크린 | `.venv/bin/python scripts/analysis/screen_large_asset_mcap200.py --list-pass` |
| `screen_large_growth_mcap200.py` | 문서 3.3절 대형 성장주 스크린 | `.venv/bin/python scripts/analysis/screen_large_growth_mcap200.py --list-pass` |

버킷 정의: `scripts_docs/stock_classification.md`.

---

## `scripts/snapshot_export/` — 버킷별 공통 스냅샷 CSV (선정은 레포 밖·CSV 활용)

| 스크립트 | 하는 일 | 예시 |
|----------|---------|------|
| `stock_snapshot_core.py` | 공통 스냅샷 DataFrame·CSV 합치기 (import 전용) | `build_stock_snapshot_df`, `write_universe_snapshot_csv` |
| `export_bucket_stock_csv.py` | 세 버킷 유니버스만 갈라 `data/analytics/*_stock.csv` (`scripts_docs/stock_classification.md` §1.3) | `.venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket all` |
| `cyclical_snapshot_terminal.py` | **단일 종목** 터미널 표(선행 수익률 등). 전체 경기순환 CSV는 위 스크립트 `--bucket cyclical` | `.venv/bin/python scripts/snapshot_export/cyclical_snapshot_terminal.py` / `--company SK하이닉스` |

스키마·경로: `scripts_docs/stock_classification.md` §1.3.

---

## 라이브러리만 (직접 실행 안 함)

`scripts/stock_db.py`, `scripts/config.py`, `scripts/quarter_terms.py`, `scripts/analysis/series_per.py` 등은 다른 스크립트에서 import 하는 모듈이다.

---

## `scripts/archive/` — 폐기된 방법론 스크립트 (참고용, 활성 파이프라인 미포함)

| 스크립트 | 폐기 이유 |
|----------|-----------|
| `screen_smid_growth.py` | 2026-07 중소형 성장주(SMID growth) 버킷 폐기. 조건 원문은 `scripts_docs/archive/smid_growth_classification.md` |
