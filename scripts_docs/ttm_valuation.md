# TTM·PER 분석 DB (`ttm_valuation.db`)

**B — 수익 기준 벨류에이션:** 분기별 재무·배당·주식수 SQLite를 읽어 **TTM·주당·PER 시계열**을 `data/analytics/ttm_valuation.db`에 쌓는다. (손익·PER 분모는 **재무 DB** 중심; **C — 분배 기준** 과 목적이 다르다.)  
**터미널에서 돌릴 파일·명령**은 [db_operations.md](./db_operations.md)(**DB 사용법**) **「B 상세 — 단계 B1 ~ B4」** 가 본문이다. 이 문서는 옵션 표·갭·보조 쿼리를 모은다.  
[db_operations.md](./db_operations.md) 의 **A — DART 적재 (A1 ~ A5)** 와는 **별도 트랙**이다. 지표를 채우려면 해당 종목·분기의 **분기 DB(A 산출물)** 가 있어야 한다.

- 지표 정의·해석: 프로젝트 루트 [financial_metrics.md](../financial_metrics.md)
- 재무 표(`sj_nm`)·계정 선택 정책: [fs_resolution.md](./fs_resolution.md) (로직 변경 시 본 DB는 **재적재** 필요)

---

## B 한 줄 순서 (수익 기준)

1. (데이터) 필요한 범위는 **A** 로 [db_operations.md](./db_operations.md) 에서 **분기 DB**를 먼저 갖춘다 — **같은 날 A1 ~ A5 전체를 끝낼 필요는 없고**, TTM에 쓸 분기만 있으면 된다.  
2. `populate_ttm_valuation.py` 로 적재  
3. (선택) `scripts/analysis/ttm_valuation_df.py` 로 터미널 조회

---

## 시총 상위 N개 / 조회 (명령 한곳)

`stock_listing.csv` **Marcap 내림차순** 상위 N개 — `update_quarter_dbs` / `populate_ttm_valuation` / `ttm_valuation_df` 가 동일 기준이다.

| 하려는 일 | 명령 (프로젝트 루트, `N`만 변경) |
|-----------|-----------------------------------|
| TTM·PER 적재 | `.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2025Q4 --limit N` |
| 터미널 표 조회 | `.venv/bin/python scripts/analysis/ttm_valuation_df.py -n N` (`--n N` / `--top-n N` 동일) |
| **성장 스크리닝** (TTM 시계열 파생) | [ttm_metric_growth.md](./ttm_metric_growth.md) · `ttm_metric_growth.py` · `ttm_metric_growth_top_n.py` · `ttm_metric_growth_lookup.py` |

**자주 나는 실수**

- **`python` 없이** `scripts/.../foo.py` 만 실행하면 `permission denied` — 반드시 `.venv/bin/python scripts/...` 형태로 실행한다.
- `ttm_valuation_df.py` 에서 `--company` 만 필수로 나오면 **옛날 버전**이다. 최신은 `--company` **또는** `-n` / `--n` / `--top-n` 중 하나가 필수다.
- `--company` 를 `populate` 에 쓰면 **`--limit` 은 무시**된다.

---

## `populate_ttm_valuation.py` 옵션

| 옵션 | 설명 |
|------|------|
| `--term` | 앵커 분기 (기본 `2025Q4`) |
| `--limit N` | 시총 순·필터 적용 후 상위 N종목만 |
| `--company 이름` | 해당 Name 만 (여러 번 가능). 지정 시 `--limit` 무시 |
| `--market` | 예: `KOSPI` (미지정이면 전체) |
| `--sleep 초` | 종목 간 대기 (기본 0.12, 주가 API 부하 완화) |
| `--init-db` | `ttm_valuation.db` 스키마만 생성, 적재 없음 |

예시 (리스트는 **A1**에서 갱신한 뒤, 적재는 재무·TTM·주가·PER 포함 기본 동작):

```bash
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --init-db
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2025Q4 --limit 10
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2025Q4 --company 삼성전자
.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2025Q4 --company 하나금융지주 --company 기아
```

그 외 플래그는 `populate_ttm_valuation.py --help` (자동화·디버깅용으로만 쓸 만한 것들).

---

## 갭·이상 징후 (대표 원인)

스크립트 모듈 docstring과 동일한 점검 포인트다.

- 재무 DB 없음 / 일부 분기만 있음 → 시계열 짧거나 `series_error`
- 계정과목 매칭 실패 → 매출·CFO 등 결측, `pl_dirty` 다수
- 액면·주식수 → `per_eps_adjusted`·PER 왜곡 (`series_per` 가 eps 쪽 보정)
- 주가 API 실패·한도 → `per_*` 결측, `meta.per_error`

---

## 한 종목·구간 백필 후 TTM (예: 하나금융지주)

**A** 로 분기 DB를 먼저 채운 뒤 본 스크립트(**B**)를 돌린다. (구간 적재는 [db_operations.md](./db_operations.md) **A2** `update_quarter_dbs_range.py` 참고.)

1. **분기 DB** (이미 했다면 생략)  
   `.venv/bin/python scripts/pipeline/update_quarter_dbs_range.py 2015Q1 2025Q4 --company 하나금융지주`

2. **지표 적재** — 앵커는 보통 최신 분기  
   `.venv/bin/python scripts/pipeline/populate_ttm_valuation.py --term 2025Q4 --company 하나금융지주`

3. **확인** — 최근 `computed_at` 배치별 행 수·분기 구간:

   ```bash
   sqlite3 data/analytics/ttm_valuation.db "
   SELECT computed_at, COUNT(*) AS n, MIN(ttm_end_term), MAX(ttm_end_term)
   FROM ttm_valuation_series
   WHERE company='하나금융지주' AND anchor_term='2025Q4'
   GROUP BY computed_at
   ORDER BY computed_at DESC
   LIMIT 3;
   "
   ```

   행 샘플 (`sqlite3` 안에서 실행):

   ```sql
   SELECT ttm_end_term, series_error, rev_ps, ni_parent_ps
   FROM ttm_valuation_series
   WHERE company='하나금융지주'
   ORDER BY computed_at DESC, ttm_end_term DESC
   LIMIT 12;
   ```

---

## `ttm_valuation_df.py` (조회만)

DB를 읽어 터미널에 표로 낸다. 적재와는 별도 실행.

```bash
.venv/bin/python scripts/analysis/ttm_valuation_df.py --company 삼성전자
.venv/bin/python scripts/analysis/ttm_valuation_df.py --n 30 --tail 5
```

`--help` 에 예시·뷰 옵션(`split` / `wide` / `transpose`)이 있다.
