# Stock Classification Logic

주식 **버킷 분류** 규칙과, 분기별 실행·분류 결과 저장 시 고려사항만 정리한다. **선정(selection)·시뮬·편입**은 본 레포 범위 밖에서(예: `data/analytics/*_stock.csv`를 외부에서 활용) 처리한다. (수치 미결 항목은 캘리브레이션으로 채운다.)

---

## 1. 공통 전제

### 1.1 대형 / 중소형

코스피200 원천 리스트 대신, **`stock_listing.csv` 시총(Marcap) 상위 200**으로 대형 유니버스를 둔다. (우선주·스팩·리츠·펀드·신탁·SPAC·KONEX·KOSDAQ GLOBAL 제외 규칙은 `scripts/stock_db.py` 의 `listing_names_ordered_by_marcap` 과 동일.)

| 조건 | 분류 |
|------|------|
| `stock_data/mcap_top_200.csv` 에 포함 | 대형주 |
| 포함되지 않음 | 중소형주 |

**갱신**  
`stock_listing.csv` 를 최신화한 뒤:

```bash
.venv/bin/python scripts/pipeline/export_mcap_top_200.py
```

**시점(as-of)**  
리밸런스(또는 분기 확정) 직전에 위 CSV를 다시 뽑아 **그 스냅샷**을 쓴다. DB·실행 로그에 **listing 파일 날짜 또는 생성 시각**을 남긴다.

### 1.2 유효 분기

문서 상의 **유효 분기**는 분석에 사용하는 분기 재무 시계열의 관측 개수(결측·품질 규칙 통과 분기)로 정의한다. 구체 규칙은 데이터 파이프라인 문서와 맞출 것.

**≥ 20** 은 **그 `as_of` 분기에 분류를 돌릴 때** “최소 이 정도 길이는 있어야 한다”는 **단순 하한**으로만 쓴다. **누적 비결측이 처음 20이 되는 분기** 같은 **별도 ‘첫 앵커’ 개념을 스펙에 둘 필요는 없다.** 경기순환은 **zero-crossing**이 본질이다.

### 1.3 공통 스냅샷 CSV (버킷별, 동일 포맷)

네 버킷 모두 **동일한 열 구조**로, 종목×분기마다 한 행씩 쌓는다. **`stock_classification.db` 는 쓰지 않는다.**

| 기본 출력 경로 | 버킷 |
|----------------|------|
| `data/analytics/cyclical_stock.csv` | 대형 경기순환 |
| `data/analytics/large_value_stock.csv` | 대형 밸류주 |
| `data/analytics/large_growth_stock.csv` | 대형 성장주 |

**한 행에 담기는 내용 (버킷 무관, 순서는 구현과 동일)**

| 구간 | 내용 | 출처 |
|------|------|------|
| 식별·앵커 | `company`, `ttm_end_term`, `per_anchor_trade_date`, `per_anchor_close` | `ttm_valuation.db` 시계열 + 상장 코드로 시세 |
| 액면·주당 | `face_value_end`, `op_ps`, `ni_parent_ps`, `capex_ps`, `cfo_ps`, `fcf_ps` | 동일 (롤4·TTM 정의는 valuation 파이프라인과 동일) |
| 배수(원본) | `per_ni_4y`, `per_ni_20d`, `per_op_4y`, `per_op_20d`, `per_rev_4y`, `per_rev_20d` | 동일 (순·영업·매출 PER, 폴백·basis 컬럼 없음) |
| 기하 누적 성장률(%) | `rev`·`op`·`ni`·`capex`·`cfo`·`fcf` 각 `*_geom_1y_mcum`, `*_geom_2y_mcum`, `*_geom_4y_mcum` | `ttm_metric_growth.db` → 해당 `ttm_end_term`에서 **첫 `batch_label` 행**만 조인 |
| 선행 수익률 | `ret_12m`, `ret_15m`, `ret_18m`(기본값; 옵션으로 개월 목록 변경 가능) | 앵커일 종가 매수 가정, N개월 후 직전 영업일 종가로 단순 수익률 |

구현: **`scripts/snapshot_export/stock_snapshot_core.py`** — `build_stock_snapshot_df`(종목별 표), `snapshot_column_order`(열 순서), `write_universe_snapshot_csv`(유니버스 합쳐 CSV). 버킷별 일괄 진입점은 `scripts/snapshot_export/export_bucket_stock_csv.py`. 선정·시뮬은 CSV를 레포 밖에서 처리; 단일 종목 터미널 확인만 `scripts/snapshot_export/cyclical_snapshot_terminal.py`.

## 3. 분류 조건

### 3.1 대형 경기순환주 (Large cyclical)

`stock_data/cyclical_manual_universe.txt`에 해당하는 종목만 §1.3 스냅샷 지표를 계산해 `data/analytics/cyclical_stock.csv`에 저장한다.

```bash
.venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket cyclical
```

---

### 3.2 대형 밸류주 (Large value)

**시총 상위 200**(`mcap_top_200.csv`, §1.1) 종목만 대상으로 한다. **분기 데이터가 28개 이상** 있어야 하고, **최근 28개 분기는 연속으로** 순이익(지배순이익 주당, DB 컬럼 `ni_parent_ps`)이 **모두 양수**여야 한다. `ttm_valuation.db` 만 쓴다. 통과 종목만 §1.3 지표를 `data/analytics/large_value_stock.csv`에 저장한다. (`large_value_passing_names`)

```bash
.venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket large_value
```

---

### 3.3 대형 성장주 (Large growth)

**시총 상위 200**(`mcap_top_200.csv`, §1.1)만 본다.

1. **분기 28개 이상** — `ttm_metric_growth.db` 의 `ttm_metric_growth_series`에서 **행 수가 가장 많은 `batch_label`** 하나만 쓰고, 그 배치에서 `ttm_end_term ≤ as_of` 인 **서로 다른 분기 수 ≥ 28**.

2. **최근 28분기 연속 영업이익 양수** — `ttm_valuation.db` 의 `ttm_valuation_series`에서 §3.2(대형 밸류)와 같이 `anchor_term = as_of`·종목별 최신 `computed_at` 배치를 고른 뒤, **가장 최근 28개 분기**마다 **영업이익 주당 `op_ps` > 0**.

3. **영업이익 성장(기하 누적 %)** — 같은 growth 배치의 **`as_of` 행**에서 `op_geom_1y_mcum`, `op_geom_2y_mcum`, `op_geom_4y_mcum` 이 모두 비결측이고 아래를 **모두** 만족:  
   - `1y_% > 0`  
   - `2y_% > 0`  
   - `4y_% > 0`  
   - `2y_% > 4y_%`  

위 1~3을 만족하면 §1.3 지표를 `data/analytics/large_growth_stock.csv`에 저장한다. (`large_growth_passing_names`)

```bash
.venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket large_growth
```

스모크·명단: `scripts/analysis/screen_large_growth_mcap200.py` (`--list-pass`).

```bash
.venv/bin/python scripts/analysis/screen_large_growth_mcap200.py
.venv/bin/python scripts/analysis/screen_large_growth_mcap200.py --list-pass
```

---

### 3.4 미분류 (Unclassified)

위 세 버킷 어디에도 해당하지 않으면 미분류. 후속 파이프라인(시뮬·선정 등)에서 별도 처리한다.

---

## 4. 실행 주기와 저장

### 4.1 주기

재무·지수가 갱신되는 리밸런스 주기(통상 **분기**)마다, 필요한 버킷에 대해 §1.3 스냅샷 CSV 를 다시 뽑는다.

### 4.2 구현 요약

스모크·명단만 볼 때: `screen_large_asset_mcap200.py`, `screen_large_growth_mcap200.py` (`--list-pass`).

선행 DB·파일: `ttm_valuation.db`, `ttm_metric_growth.db`, `mcap_top_200.csv`, `stock_listing.csv`, 경기순환 수동 유니버스 `cyclical_manual_universe.txt`(§3.1).

---

## 5. 변경 이력

| 날짜 | 내용 |
|------|------|
| (최초) | `docs/종목분류와선정로직.txt` 기반으로 통합·보강 |
| — | 선정(selection) 내용 분리, 문서명·제목을 분류 전용으로 정리 |
| — | 대형 경기순환 5번(교차 간격 균등) 제거, 보조 필터는 탐색용으로만 기술 |
| — | 경기순환: 매출 경로 제거, 영업 `1y_%`만 + 결측 건너뛰기 명시 |
| — | 경기순환 항목 4·5를 하나로 합쳐 번호상 5번 제거(내용은 유지) |
| — | 유효 분기 하한 28 → 20 (대형 경기순환·대형 밸류주) |
| — | 대형 유니버스: 코스피200 → `stock_listing` 시총 상위 200 (`mcap_top_200.csv`) |
| — | 경기순환 2번에서 영업 1y_% 비결측 정의 괄호 제거(선정 단계에서 정합) |
| — | 유효 분기 ≥20: ‘첫 앵커’ 별도 정의 없이 as_of 시점 하한만 명시 |
| — | 경기순환 zero-crossing: 달력 연속·연속 교차 압축 후 **`MIN_CROSS`~`MAX_CROSS` 밴드** (문서·탐색용) |
| — | §3.1: 유니버스를 `cyclical_manual_universe.txt` 단일 파일로 고정, mcap/≥20/교차 밴드 **선별 제거** |
| 2026-04 | `scripts/selection/` → `scripts/snapshot_export/` (선정·시뮬 비범위). `cyclical_snapshot_terminal.py`·`export_bucket_stock_csv.py`만 유지 |
| 2026-04 | `stock_classification.db`·`populate_stock_classification.py`·`apply_cyclical_manual_filter.py` 제거. §1.3 공통 스냅샷 CSV + `export_bucket_stock_csv.py` |
| 2026-04 | 경기순환 수동 리스트: `cyclical_manual_keep.txt`·`cyclical_manual_remove.txt` → **`cyclical_manual_universe.txt`** 통합. CLI `--cyclical-manual` |
| 2026-04 | §3.2: 시총200·28분기 이상·**최근 28분기 연속** 순이익 양수 (`ni_parent_ps`) |
| — | §3.2: **valuation DB만**·앵커 **≥28**; growth 제거 |
| — | §3.3·§3.4: **앵커 ≥28** 분기(`ttm_metric_growth_series`·최대 `batch_label`) |
| — | §3.3 스모크: `screen_large_growth_mcap200.py` |
| 2026-04 | §3.3: 영업만 — **최근 28분기 `op_ps` > 0** + `as_of` 행 `op_geom_*` 네 부등식 (`large_growth_passing_names`) |
| 2026-04 | §3.4: §3.3과 동일 구조·**ni_parent_ps 28분기** + **`ni_geom_*`** 부등식·비대형 유니버스; `screen_smid_growth.py` |
| 2026-04 | §3.2 명칭·출력: **대형 밸류주** — `large_value_stock.csv`, `--bucket large_value`, `large_value_passing_names` |
| 2026-07 | §3.4(중소형 성장주) 제거 — US 프로젝트와 동일한 경기순환/대형밸류/대형성장 3버킷 체계로 정리. 원문은 `scripts_docs/archive/smid_growth_classification.md`, 스크립트는 `scripts/archive/screen_smid_growth.py`로 이동 |
