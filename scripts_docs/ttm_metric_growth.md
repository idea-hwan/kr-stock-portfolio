# TTM 성장률 스크리닝 (분기성장률 · `1y_%`~`8y_%`)

`data/analytics/ttm_valuation.db` 의 종목별 TTM 시계열을 읽어, **분기당 수정 누적 성장률**과 **최근 4·8·16·32분기 창의 누적 성장 지표**(`1y_%` … `8y_%`)를 만든다.  
DART·분기 원천 DB를 **다시 부르지 않는다** — 선행으로 [B — `ttm_valuation` 적재](./ttm_valuation.md)가 필요하다.

```mermaid
flowchart LR
  subgraph 선행
    A1[분기 SQLite A]
    B1[populate_ttm_valuation]
  end
  DB[(ttm_valuation.db)]
  PY[ttm_metric_growth.py]
  A1 --> B1
  B1 --> DB
  DB --> PY
  PY --> OUT[터미널 표]
```

| 항목 | 위치 |
|------|------|
| 로직·컬럼 생성 | `scripts/screening/ttm_metric_growth.py` (`build_ttm_metric_growth_df`) |
| 단일 종목 CLI | 동일 모듈 `main` |
| 시총 상위 N 배치 | `scripts/screening/ttm_metric_growth_top_n.py` (행이 있으면 **항상** `ttm_metric_growth.db` 적재) |
| **DB만 읽어 개별 종목 표시** | `scripts/screening/ttm_metric_growth_lookup.py` (`load_company_growth_df`) |

실행은 프로젝트 루트에서 **`.venv/bin/python scripts/screening/…`** 형태를 쓴다. (`bin/ttm_metric_growth*` 셸 스크립트는 같은 명령을 감싼 선택 사항이며, `top_n` 은 인자 없이 실행 시 `--top-n 2500` 을 넣어 준다.)

---

## 터미널 `split` 화면 (표기 그대로)

`--view split`(기본)일 때 **블록 제목과 열 헤더**는 아래와 같다. (DB·CSV·DataFrame 은 같은 의미의 **스네이크 케이스** 컬럼명을 쓴다.)

| 블록 | 의미 |
|------|------|
| `[1] 매출/주` | 매출 per share (롤4·액면 보정) |
| `[2] 영업/주` | 영업이익 per share |
| `[3] 지배순/주` | 지배순이익 per share |
| `[4] CFO` | CFO TTM (원) |
| `[5] Capex` | Capex TTM (원) |
| `[6] FCF` | FCF TTM (원) |

각 블록의 **열 이름(터미널에 찍히는 문자)**:

| 헤더 | 의미(요약) |
|------|------------|
| `분기` | TTM 스냅샷 분기 `ttm_end_term` |
| `분기성장률(%)` | 해당 분기의 **수정 누적** 분기 성장률 % (앵커·span 규칙 적용, DB: `*_cum_geom_pct`) |
| `span` | 위 성장률이 잡힌 구간의 분기 수 (DB: `*_span_q`) |
| `1y_%` | 최근 4분기 창의 **누적 성장 지표** %, \(P=\prod(1+g)\), \(P^{1/4}-1\) (DB: `*_geom_1y_mcum`) |
| `1y_q_empty` | 그 4분기 창에서 `분기성장률`이 비어 있던 분기 수 |
| `1y_q_minus` | 그 창에서 TTM **원시값**이 음수였던 분기 수 |
| `2y_%`, `2y_q_empty`, `2y_q_minus` | 동일 정의, 창 **8분기** (DB: `*_geom_2y_mcum` 등) |
| `4y_*` | 창 **16분기** |
| `8y_*` | 창 **32분기** |

`—` 는 “값 없음”(계산 스킵 또는 비표시).

`--view wide` 는 **한 행에 모든 컬럼**을 펼친다(같은 스네이크 케이스 이름).

---

## 데이터·종목 범위

- **입력:** `ttm_valuation_series` (컬럼은 `scripts/analysis/ttm_valuation_df.py` 와 동일)
- **P/L 주당**(매출·영업·지배순): 롤4 `rev_ps` / `op_ps` / `ni_parent_ps` 에 대해 PER 축과 맞춘 **액면 보정** 후 성장률 계산
- **현금**(CFO·Capex·FCF): `ttm_cfo_krw` / `ttm_capex_krw` / `ttm_fcf_krw` (원 TTM, 액면 보정 없음)

**배치 스크립트**의 종목 순서는 `stock_listing.csv` **Marcap 내림차순**이며, 우선주·이름 스팩·리츠·펀드·신탁·SPAC(부) 등은 `scripts/stock_db.py` 의 `listing_names_ordered_by_marcap()` **기본 제외**와 동일하다. (`populate_ttm_valuation` · `ttm_valuation_df` 와 같은 “허용 유니버스” 개념 — [db.md](./db.md) 「적재·평가 대상 종목 선정」)

---

## 규칙 요약 — `분기성장률(%)` (`*_cum_geom_pct`)

적자·0 구간은 단순 QoQ로 잇지 않고 **보류**한다. 흑자 복귀 시 등은 **마지막 양수 앵커 ~ 당기** 구간 비율로 **분기당 기하평균 %** \((R^{1/k}-1)\times 100\) 를 둔다.  
(내부적으로 연속 양수일 때의 QoQ%는 쓰지만 **결과 테이블에는 넣지 않는다**.)

자세한 분기 케이스는 `ttm_metric_growth.py` 모듈 상단 docstring을 본다.

---

## 규칙 요약 — `1y_%` … `8y_%` (`*_geom_{1y,2y,4y,8y}_mcum`)

각 지표마다 **같은 식**으로, 기간만 \(k\) 분기(4 / 8 / 16 / 32)로 늘린다.

1. 당기 인덱스 \(i\) 기준 창 \([i-k+1,\, i]\) 의 각 분기에 대해 \(g_t = (\text{분기성장률}_t) / 100\) (소수). **비어 있으면 \(g_t = 0\)**.
2. 창 안에서 **실제 인덱스가 \([0,n)\)에 속한 칸이 전부** 분기성장률이 비어 있으면 지표는 비움.
3. \(P = \prod_t (1 + g_t)\). \(P \le 0\) 이면 비움.
4. **`1y_%` … `8y_%` 각 열의 값** \(= \bigl(P^{1/k} - 1\bigr) \times 100\) (여기서 \(k\)는 4·8·16·32).

**이름 정리:** 화면·문서에서는 `1y_%` / `2y_%` … 로 부르고, 코드·SQLite 컬럼은 `rev_geom_1y_mcum`, `rev_geom_2y_mcum`, … 형태다 (`rev` 자리에 `op`, `ni`, `cfo`, `capex`, `fcf`).

---

## `q_empty` · `q_minus`

같은 \(k\)분기 창에 대해:

| DB·wide 컬럼 패턴 | 의미 |
|-------------------|------|
| `{prefix}_1y_q_empty` 등 | \([0,n)\) 안에서 **분기성장률(`cum`)** 이 비어 있던 분기 수 |
| `{prefix}_1y_q_minus` 등 | 같은 창에서 TTM **원시값**이 **음수(\(<0\))** 인 분기 수 |

---

## 터미널 헤더 ↔ SQLite·DataFrame 컬럼 (요약)

| 터미널 `split` 헤더 | 컬럼 이름 패턴 |
|---------------------|----------------|
| 분기 | `ttm_end_term` |
| 분기성장률(%) | `{prefix}_cum_geom_pct` |
| span | `{prefix}_span_q` |
| `1y_%` | `{prefix}_geom_1y_mcum` |
| `1y_q_empty` | `{prefix}_1y_q_empty` |
| `1y_q_minus` | `{prefix}_1y_q_minus` |
| `2y_%` … `8y_%` | `{prefix}_geom_2y_mcum` … `{prefix}_geom_8y_mcum` |
| `2y_q_empty` … | `{prefix}_2y_q_empty`, `{prefix}_2y_q_minus`, … (4y·8y 동일) |

| `prefix` | 블록 |
|----------|------|
| `rev` | `[1]` 매출/주 |
| `op` | `[2]` 영업/주 |
| `ni` | `[3]` 지배순/주 |
| `cfo` | `[4]` CFO |
| `capex` | `[5]` Capex |
| `fcf` | `[6]` FCF |

배치 적재 시 **앞쪽 메타 열:** `batch_label`, `company`, `source_anchor_term`, `source_ttm_computed_at`, `source_top_n`, 그다음 `ttm_end_term` 및 위 성장률 열들(현재 스키마 **약 90열**).

---

## CLI — 단일 종목

프로젝트 루트에서 (가상환경 활성화 여부와 관계없이 인터프리터 경로만 맞추면 됨):

```bash
.venv/bin/python scripts/screening/ttm_metric_growth.py --company 삼성전자
.venv/bin/python scripts/screening/ttm_metric_growth.py --company 삼성전자 --view wide
.venv/bin/python scripts/screening/ttm_metric_growth.py --help
```

가상환경을 이미 켠 터미널이면 `python scripts/screening/ttm_metric_growth.py …` 로 같다.

| 옵션 | 설명 |
|------|------|
| `--company` | `stock_listing` **Name** 과 동일한 종목명 |
| `--db` | `ttm_valuation.db` 경로 (기본 `data/analytics/ttm_valuation.db`) |
| `--anchor-term` / `--computed-at` | `ttm_valuation_df` 와 동일 필터 |
| `--view` | `split`(기본) · `wide` |

---

## CLI — 시총 상위 N (배치)

```bash
.venv/bin/python scripts/screening/ttm_metric_growth_top_n.py --top-n 2500
.venv/bin/python scripts/screening/ttm_metric_growth_top_n.py --top-n 10
.venv/bin/python scripts/screening/ttm_metric_growth_top_n.py --top-n 100 --anchor-term 2025Q4 --market KOSPI
.venv/bin/python scripts/screening/ttm_metric_growth_top_n.py --help
```

계산된 행이 있으면 **항상** `data/analytics/ttm_metric_growth.db` 에 적재한다. 전 유니버스에 가깝게 돌릴 때는 `--top-n 2500` 등 목표 개수를 직접 지정하면 된다. (venv 활성화 후에는 `python scripts/screening/ttm_metric_growth_top_n.py …` 로 동일.)

| 옵션 | 설명 |
|------|------|
| `--top-n` | 시총 순 앞에서 N종 (`python` 직접 시 기본 10) |
| `--batch-label` | SQLite 배치 구분 (미지정 시 UTC 시각). **같은 라벨은 기본 DELETE 후 INSERT** |
| `--sqlite-append-only` | SQLite만 DELETE 없이 append (동일 `batch_label` 중복 허용) |
| `--market` | 예: `KOSPI` / `KOSDAQ` (미지정 시 전체) |
| `--fail-fast` | 첫 예외에서 중단 |
| `--quiet` | 진행 로그 최소화 |

### SQLite 스키마 (배치)

- **파일:** `data/analytics/ttm_metric_growth.db` (고정, 배치로 행이 생기면 **매번** 적재)
- **테이블:** `ttm_metric_growth_series`
- **메타 열:** `batch_label`, `company`, `source_anchor_term`, `source_ttm_computed_at`, `source_top_n`, `ttm_end_term`, 이후 `{prefix}_…` 성장률 열

`ttm_valuation.db` 와는 **별도 파일**로 두어 원천(TTM)과 파생(성장)을 분리한다.

#### 적재 확인 (요약)

```bash
sqlite3 data/analytics/ttm_metric_growth.db "
SELECT COUNT(*) AS total_rows FROM ttm_metric_growth_series;
"
sqlite3 data/analytics/ttm_metric_growth.db "
SELECT batch_label, COUNT(*) AS n_rows, COUNT(DISTINCT company) AS n_companies
FROM ttm_metric_growth_series
GROUP BY batch_label
ORDER BY n_rows DESC
LIMIT 8;
"
```

- 배치 실행 직후 stderr에 `batch_label=…` 가 찍히므로, **그 문자열**으로 `WHERE batch_label = '…'` 필터하는 것이 가장 확실하다.
- 테스트용 소량 배치(`source_top_n` 이 작은 행 등)가 같이 있을 수 있어, **행 수가 가장 큰 `batch_label`** 이 보통 전 종목 풀 리빌드다.

#### 조회 예 (최대 배치 자동 선택)

```sql
SELECT company, ttm_end_term, rev_cum_geom_pct, rev_geom_1y_mcum, fcf_geom_1y_mcum
FROM ttm_metric_growth_series
WHERE batch_label = (
  SELECT batch_label FROM ttm_metric_growth_series
  GROUP BY batch_label ORDER BY COUNT(*) DESC LIMIT 1
)
  AND company = '삼성전자'
ORDER BY ttm_end_term DESC
LIMIT 4;
```

SQLite에 저장되는 **성장률 계열** 수치는 **퍼센트 포인트**(예: `2.83` ≒ 2.83%)이며, `q_empty`·`q_minus`·`span_q` 는 **정수 의미**의 카운트다.

DB에 행이 없는 종목은 **빈 결과로 스킵**되며, 요약에 `empty` 로 잡힌다.

---

## DB에서 개별 종목 조회 (재계산 없음)

배치로 `ttm_metric_growth.db` 에 넣어 둔 뒤, **TTM DB를 다시 읽지 않고** 조회만 할 때 쓴다. 터미널 출력 형식은 `ttm_metric_growth.py` 의 **split / wide** 와 동일하다.

```bash
.venv/bin/python scripts/screening/ttm_metric_growth_lookup.py --company 삼성전자
.venv/bin/python scripts/screening/ttm_metric_growth_lookup.py --company 삼성전자 --view wide
.venv/bin/python scripts/screening/ttm_metric_growth_lookup.py --list-batches
.venv/bin/python scripts/screening/ttm_metric_growth_lookup.py --company 삼성전자 --batch-label '2026-04-08T030342Z'
```

| 옵션 | 설명 |
|------|------|
| `--company` | 필수 (`--list-batches` 가 아닐 때) |
| `--growth-db` | 기본 `data/analytics/ttm_metric_growth.db` |
| `--batch-label` | 생략 시 **행 수가 가장 많은** `batch_label` 자동 |
| `--view` | `split`(기본) · `wide` |
| `--list-batches` | 배치별 `n_rows` · `n_companies` 표만 출력 |

첫 줄 요약(`growth_db`·`batch_label`·행 수)은 **stderr**, 표 본문은 **stdout** 이다.

---

## 노트북·모듈

**원천 TTM에서 즉시 계산:**

```python
from scripts.screening.ttm_metric_growth import build_ttm_metric_growth_df

df = build_ttm_metric_growth_df("삼성전자", anchor_term="2025Q4")
```

**적재된 성장 DB만 읽기 (DataFrame, 노트북 표에 적합):**

```python
from scripts.screening.ttm_metric_growth_lookup import load_company_growth_df

df = load_company_growth_df("삼성전자")
# df.set_index("ttm_end_term").tail(12)
# Jupyter: from IPython.display import display; display(df)
```

---

## 관련 문서

- [db.md](./db.md) — 디렉터리·원천·종목 선정
- [db_operations.md](./db_operations.md) — A/B 사용법
- [ttm_valuation.md](./ttm_valuation.md) — `ttm_valuation.db` 적재·조회
