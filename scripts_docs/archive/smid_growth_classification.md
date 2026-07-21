# 중소형 성장주 (SMID growth) — 폐기된 버킷

> 2026-07 버킷 체계를 경기순환/대형밸류/대형성장 3개로 정리하면서 제외됨(US `us-stock-portfolio`와 동일한 3분류 체계에 맞추기 위함). 아래는 `scripts_docs/stock_classification.md` §3.4에 있던 원문 그대로의 기록 — 방법론 참고용으로만 보존.

---

### 3.4 중소형 성장주 (SMID growth)

§3.3 **대형 성장주**와 **동일한 절차·데이터**이되, 아래만 다르다.

1. **유니버스** — `listing_pipeline_allowed_names()` 에서 **`mcap_top_200.csv` 이름을 뺀 전체** (시총 상위 200이 아닌 허용 상장 종목). 통과 명단은 **이름 정렬** 순.

2. **순이익 축** — §3.3의 영업이익 대신 **지배주주순이익**으로 동일 조건을 적용한다.
   - **최근 28분기 연속** `ttm_valuation_series` 의 **`ni_parent_ps` > 0** (§3.2 대형 밸류·§3.3과 같은 `anchor_term = as_of`·종목별 최신 `computed_at`).
   - **`as_of` 행**에서 `ni_geom_1y_mcum` · `ni_geom_2y_mcum` · `ni_geom_4y_mcum` 비결측이고
     `1y_% > 0`, `2y_% > 0`, `4y_% > 0`, `2y_% > 4y_%` **모두** 만족.

3. 유동성 기준 컷 — **추후 추가** (선정·시뮬 문서와 맞출 것)

저장: `export_bucket_stock_csv.py --bucket smid_growth` (`smid_growth_passing_names`).

```bash
.venv/bin/python scripts/snapshot_export/export_bucket_stock_csv.py --bucket smid_growth
```

**스모크·목록** — `scripts/analysis/screen_smid_growth.py` (`--list-pass`).

```bash
.venv/bin/python scripts/analysis/screen_smid_growth.py
.venv/bin/python scripts/analysis/screen_smid_growth.py --list-pass
```

스크립트 원본은 `scripts/archive/screen_smid_growth.py`로 이동됨.
