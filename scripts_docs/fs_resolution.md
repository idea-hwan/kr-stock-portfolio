# 재무 DB → 지표 파이프라인 (표 선택·계정 매핑)

`data/financial_statement/<분기>.db` 는 DART 제출 형태 그대로 들어오므로, **회사·분기·개정 시점**에 따라 같은 지표라도 **다른 `sj_nm`(표 이름)** 이나 **`account_id`(XBRL 태그)** 에 실릴 수 있다.  
분석 스크립트(`scripts/analysis/fs_metrics.py`, 이를 쓰는 `per_share_roll4.py` 등)는 아래 **고정된 우선순위**로 “무엇을 볼지”를 정한다.

---

## 1. 데이터 적재 파이프라인 (변경 없음)

적재 순서·파일 구조는 [db_operations.md](./db_operations.md)(사용법), [db.md](./db.md) 와 동일하다.

1. `update_quarter_dbs.py` 등으로 분기별 SQLite 채움  
2. 테이블 = 종목명, 행 = `sj_nm` + `account_id` + `account_nm` + `thstrm_amount` …

**이 문서는 2번 이후**, “지표를 뽑을 때 어떤 행을 고를지”만 다룬다.

### 1.1 배당·주식 원천 품질 (개정·계정 작업과 같은 축)

재무 `sj_nm` / `account_id` 를 손보는 것과 **별개로**, `populate_ttm_valuation` → `per_share_roll4._panel` 은 **배당·주식수 DB**도 읽는다.

| 소스 | 쓰는 곳 (요지) |
|------|----------------|
| `data/dividend/*.db` | 액면(`se` = `주당액면가액(원)`), 참고용 주당순이익(`se` = `주당순이익(원)` 등) |
| `data/stocks/*.db` | `istc_totqy`·`se`(보통주 우선) |

**깨진 적재**로 분기 파일 안에 테이블은 있는데 **행이 없고 `index` 컬럼만 있는** 경우가 있다. (예: `data/dividend/2020Q3.db` 의 `LG에너지솔루션` — `CREATE TABLE` 에 `se`·`thstrm` 이 없음.)  
이때 예전에는 `compute:'se'` 로 **전 종목 적재가 통째로 실패**할 수 있었고, 코드에서는 **`se` 없음·빈 표면 결측으로 건너뛰도록** 방어한다. **데이터는 그래도 고치는 게 맞다.**

**점검 (복붙용):**

```bash
sqlite3 data/dividend/2020Q3.db "PRAGMA table_info('LG에너지솔루션');"
sqlite3 data/stocks/2025Q4.db "PRAGMA table_info('LG에너지솔루션');"
```

`se` / `thstrm` 이 없거나 테이블이 비어 있으면 해당 연·분기만 **배당(또는 주식) 재적재**:

```bash
.venv/bin/python scripts/pipeline/update_quarter_dbs.py 2020 3 --company LG에너지솔루션 --types dividend
```

적재 실패 목록은 `populate` 실행 후 `data/analytics/ttm_valuation_gaps_<앵커>_<날짜>.json` 의 `failures` 를 본다.  
**운영 습관:** 재무 `SPECS`·`SJ_NM` 을 손볼 때와 같이, **이상 종목이 나오면 배당/주식 파일도 같은 분기 범위로 스팟 점검**해 두면 `ttm_valuation` 쪽 디버깅이 줄어든다.

---

## 2. 레이어 A — 어떤 표(`sj_nm`)를 볼 것인가

코드: `fs_metrics.SJ_NM_FALLBACK`, `_sj_nm_candidates()`.

| 재무제표 종류(논리) | 시도 순서 (`sj_nm`) |
|---------------------|----------------------|
| 손익(매출·이익 등) | `손익계산서` → `연결손익계산서` → `포괄손익계산서` → `연결포괄손익계산서` |
| 현금흐름 | `현금흐름표` → `연결현금흐름표` |
| 재무상태 | `재무상태표` → `연결재무상태표` |

- **같은 분기 DB 안에서, 위 순서대로 첫 번째로 비어 있지 않은 표**에서 계정을 찾는다.  
- 예: 일부 회사는 손익이 **`포괄손익계산서`에만** 있고 `손익계산서` 행이 없다 → 예전에는 손익이 전부 빈 값이었고, 포괄손익을 넣은 뒤로 채워진다.  
- **회사마다 실제로 존재하는 `sj_nm`만** 쓰이고, 없는 이름은 자동으로 건너뛴다.

**점검 명령:**

```bash
.venv/bin/python scripts/analysis/fs_metrics.py --probe-sj --company "<종목명>" --term 2024Q4
```

---

## 3. 레이어 B — 어떤 계정(`account_id` / 이름)을 볼 것인가 (개정·혼용)

코드: `fs_metrics.SPECS`, `_expand_account_ids()`, `_pick_from_df()`.

대략적인 순서는 다음과 같다.

1. **`account_id` 정확 일치** — `SPECS`에 나열한 순서대로 시도  
2. **`ifrs-full_*` ↔ `ifrs_*`** — XBRL 개정·혼용에 따라 `_expand_account_ids`가 짝을 붙여 추가 시도  
3. **`account_nm` 공백 제거 후 정확 일치** (예: `수익(매출액)`)  
4. **`contains` 부분일치** (일부 지표만, 과도한 매칭을 피하기 위해 제한적으로 사용)

- **개정으로 태그가 바뀐 경우** → `SPECS`의 해당 지표 튜플에 **새 `account_id`를 앞쪽 후보로 추가**하는 것이 정석이다.  
- **한국어 계정명만 있는 구공시** → `stripped_names` / `contains`로 보완.

**점검 명령 (손익·포괄손익 계정 덤프):**

```bash
.venv/bin/python scripts/analysis/fs_metrics.py --probe-pl --company "<종목명>" --term 2024Q4
.venv/bin/python scripts/analysis/fs_metrics.py --probe-pl --company "<종목명>" --term 2024Q4 --probe-filter Revenue
```

---

## 4. 회사마다 다를 때의 운영

| 증상 | 우선 확인 |
|------|-----------|
| CFO·FCF만 나오고 매출·이익이 전부 비음 | `--probe-sj` 로 손익이 어떤 `sj_nm`에 있는지 → `SJ_NM_FALLBACK`에 표가 빠지지 않았는지 |
| 특정 종목만 한 지표가 비음 | `--probe-pl` + `--probe-filter` 로 실제 `account_id` / `account_nm` 확인 → `SPECS`에 id·이름 후보 추가 |
| 개정·신규 태그 | DART/XBRL 공지 또는 표본 공시 몇 건의 `account_id`를 모아 `SPECS` 반영 |

코드 변경 후 **이미 적재된 분석 DB**(`ttm_valuation.db` 등)는 과거 스냅샷이므로, 로직을 고치면 **`populate_ttm_valuation.py` 등 재적재**가 필요하다.

### 4.1 금융업 — 매출·매출총이익이 비는 경우 (매핑 한계가 아닌 구조)

은행·일부 금융지주 등은 DART 손익이 **이자순익·수수료** 중심이라, 본 파이프라인이 가정하는 **일반기업형 `revenue` / `gross_profit`** 과 같은 계정이 없거나 이름·구조가 다르다.

- **`fs_metrics.SPECS`** 는 제조·서비스 등에서 흔한 `매출액`·`매출총이익` 태그를 우선한다.  
- 금융 공시와 맞지 않으면 **`rev_ps`·`gp_ps`(및 FY 동일)** 가 비고, **`operating_income`·`net_income_parent`** 등은 잡히는 식으로 나올 수 있다.  
- **의도:** 금융을 억지로 일반 `revenue`/`gross_profit`에 끼워 넣지 않는다. 배수는 **P/영업·PER·(은행별로 별도 설계한 지표)** 등으로 보는 편이 맞다.  
- 계정명을 더 넓히고 싶다면 `--probe-pl` 로 실제 `account_id` / `account_nm` 을 확인한 뒤 **`SPECS`에 금융 전용 후보를 추가**하는 식으로 확장한다.

### 4.2 지주회사 등 — 매출총이익 줄이 없는 경우

지주·지분법 비중이 큰 회사는 손익에 **매출(영업수익)은 있으나 `매출원가`·`매출총이익`(GrossProfit) 줄이 아예 없는** 공시가 흔하다. (예: SK스퀘어 — `ifrs-full_Revenue` / 매출액은 있으나 GrossProfit·매출원가 행 없음)

- DB에 **해당 계정 행이 없으면** `_pick_from_df` 가 값을 낼 수 없다 → **`gp_ps`·`fy_gp_ps`·P÷TTM 매출총이익** 이 비는 것이 **정상**이다.  
- **오류가 아니라 공시 형식 차이**이므로, 같은 종목은 **P/매출·P/영업·PER** 위주로 해석하면 된다.  
- “매총이 없을 때 매총=매출로 간주” 같은 **합성 지표**는 정책으로 넣을 수 있으나, 그 경우 P/매총과 P/매출이 사실상 중복에 가깝다.

---

## 5. 한눈에 보는 의존 관계

```text
financial_statement/*.db ──► fs_metrics._pick_from_df (sj_nm → 계정)
dividend/*.db, stocks/*.db ──► per_share_roll4._panel (액면·주당순이익·istc)
        │
        ▼
   per_share_roll4 / populate_ttm_valuation → data/analytics/ttm_valuation.db
```

**B — 수익 기준 벨류에이션** CLI·재적재·확인은 [ttm_valuation.md](./ttm_valuation.md) 를 본다.

정책을 바꿀 때는 **`SJ_NM_FALLBACK` / `SPECS` / 본 문서**를 함께 맞추면 된다.
