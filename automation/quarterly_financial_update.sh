#!/bin/bash
# 분기 재무 원본 적재 (DART, 정식 분기·반기·사업보고서) — 매일 자동 호출해도
# 안전한 버전(마감일 기준 자동 스킵).
#
# scripts_docs/db_operations.md 의 A1 → A2 → A5 → B2 순서 + 유니버스 스냅샷 갱신:
#   1. KRX 상장 리스트 갱신 (update_stock_listing.py)
#   1-x. mcap_top_200.csv 갱신 (export_mcap_top_200.py) — scripts_docs/
#        stock_classification.md §1.1 "시점(as-of): 리밸런스(또는 분기 확정)
#        직전에 다시 뽑아 그 스냅샷을 쓴다"를 그대로 따름. A2/B2의 --top-n/
#        --limit 자체는 stock_listing.csv 로 그때그때 다시 랭킹을 매겨서 이
#        파일을 안 읽지만, build_current_prices.py·build_mcap200_factor_panel.py·
#        build_dashboard.py·build_pit_buckets.py 등 daily_update.sh 쪽은 이 정적
#        스냅샷을 그대로 읽는다 — 여기서 안 갱신하면 daily 쪽 유니버스가 새
#        분기 데이터·최신 시총 순위와 어긋난 채로 굳어버린다. 유니버스가
#        바뀌면(신규 상장 진입, 제외 룰 변경 등) pit_buckets·factor_panel도
#        재생성 대상이라는 점은 stock_classification.md 변경 이력 참고.
#   2. 대상 연·분기 재무·배당·주식수 DB 적재 (update_quarter_dbs.py)
#   3. 해당 분기 오딧 (audit_data_dbs.py, 그 분기만 스코프)
#   4. TTM·PER 재계산 (populate_ttm_valuation.py)
#
# 왜 "마감일 다음날" 기준인가 (2026-07-24 삼성전자로 실측): 정식 보고서는
# 대형주도 마감일 당일에 몰아서 내는 경우가 흔하다(2026Q1 삼성전자: 5/15 당일
# 제출, 그 전엔 계속 비어 있었음). 마감일 당일 오전에 확인하면 그날 늦게
# 제출하는 곳을 놓칠 수 있어서, automation/quarterly_term_window.py 의
# formal_target_term() 은 "마감일+1일"(그날 하루치가 다 올라온 뒤) 또는
# "마감일+8일(지각 제출 정리용)" 두 시점에만 분기를 반환하고, 그 외엔 DART를
# 부르지 않고 바로 스킵한다 — 스케줄러가 매일 불러도 낭비 없음.
# (마감 전에 미리 부분적으로라도 걷고 싶으면 잠정실적 트랙 —
# scripts/pipeline/collect_preliminary_earnings.py — 를 따로 쓴다. 매출액·
# 영업이익만 나오는 얼리 시그널이고 정식 재무제표를 대체하지 않는다.)
#
# 반복 실행 자체도 안전(멱등)하다 — scripts/stock_db.py의 create_finstate_db
# 등은 회사별로 개별 실행되고(if_exists="replace"), 아직 공시가 없으면 "조회
# 결과 없음 — 기존 테이블 유지"로 스킵하고 예외도 잡아서 넘어간다.
#
# 기본 범위는 --top-n 200 (mcap_top_200.csv, 현재 대시보드가 쓰는 유니버스와
# 동일) — 전 종목(2000개 이상) 재조회는 종목당 2초 sleep 누적으로 몇 시간이
# 걸려 자동 실행에 부적합하다. 전 종목이 필요하면 --full 로 전환.
#
# A3(이름만 바뀐 종목)·A4(신규 상장 백필)는 조건부·판단이 필요해 여기서 자동
# 실행하지 않는다 — 3단계 오딧 로그를 보고 필요하면 아래 두 스크립트를 직접 돌릴 것:
#   .venv/bin/python scripts/pipeline/rename_company_tables.py --dry-run
#   .venv/bin/python scripts/pipeline/backfill_new_listing.py
#
# data/analytics/, data/financial_statement/, data/stocks/, data/dividend/ 는
# 전부 .gitignore 대상이라 이 스크립트가 여기까진 git commit/push를 하지
# 않는다 — 다음 automation/daily_update.sh 실행 때 갱신된 ttm_valuation.db 가
# 패널·PIT·대시보드에 자동 반영된다.
#
# 반대로 stock_data/stock_listing.csv·mcap_top_200.csv 는 git 추적 대상이라
# (data/analytics와 다름) A1·1-x 갱신으로 바뀌었으면 이 스크립트가 직접
# commit+push 한다(daily_update.sh 는 docs/index.html만 처리해서 이 두 파일은
# 안 건드림). stock_data/backups/ 의 타임스탬프 백업은 .gitignore 대상이라
# 커밋되지 않는다.
#
# 사용법:
#   automation/quarterly_financial_update.sh                    # 오늘 날짜로 자동 판단, top-n 200
#   automation/quarterly_financial_update.sh 2026 2              # 분기 강제 지정, top-n 200
#   automation/quarterly_financial_update.sh 2026 2 --full       # 분기 지정 + 전 종목

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

LOG_DIR="$ROOT/automation/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y%m%d)_quarterly.log"

TOPN_ARGS=(--top-n 200)

if [[ $# -ge 2 ]]; then
    YEAR="$1"
    QUARTER="$2"
    if [[ "${3:-}" == "--full" ]]; then
        TOPN_ARGS=()
    fi
else
    TERM="$($PY automation/quarterly_term_window.py)" || TERM=""
    if [[ -z "$TERM" ]]; then
        {
            echo "===== quarterly_financial_update $(date '+%Y-%m-%d %H:%M:%S') ====="
            echo "현재 활성 공시 창 아님 (분기보고서 4/1~5/15, 반기 7/1~8/15, 3분기 10/1~11/15, 사업보고서 1/1~3/31) — 스킵"
        } >> "$LOG_FILE" 2>&1
        echo "활성 공시 창 아님 — 스킵 (로그: $LOG_FILE)"
        exit 0
    fi
    YEAR="${TERM%%Q*}"
    QUARTER="${TERM##*Q}"
fi

TERM="${YEAR}Q${QUARTER}"

SCOPE_LABEL="전종목"
[[ ${#TOPN_ARGS[@]} -gt 0 ]] && SCOPE_LABEL="${TOPN_ARGS[*]}"

{
    echo "===== quarterly_financial_update 시작 ($TERM, 범위: $SCOPE_LABEL) $(date '+%Y-%m-%d %H:%M:%S') ====="

    echo "--- A1: 상장 리스트 갱신 ---"
    "$PY" scripts/pipeline/update_stock_listing.py

    if [[ -s stock_data/new_codes_since_stock_csv.txt ]]; then
        N_NEW="$(grep -c . stock_data/new_codes_since_stock_csv.txt || true)"
        echo ">>> 신규 상장 종목 대기 ${N_NEW}개 (stock_data/new_codes_since_stock_csv.txt) — 필요하면 backfill_new_listing.py 직접 실행 (자동 실행 안 됨)"
    fi

    echo "--- 1-x: mcap_top_200.csv 스냅샷 갱신 ---"
    "$PY" scripts/pipeline/export_mcap_top_200.py

    echo "--- A2: $TERM 적재 ---"
    "$PY" scripts/pipeline/update_quarter_dbs.py "$YEAR" "$QUARTER" "${TOPN_ARGS[@]}"

    echo "--- A5: $TERM 오딧 ---"
    "$PY" scripts/pipeline/audit_data_dbs.py --start-term "$TERM" --end-term "$TERM"

    echo "--- B2: TTM·PER 재계산 (--term $TERM) ---"
    "$PY" scripts/pipeline/populate_ttm_valuation.py --term "$TERM" "${TOPN_ARGS[@]/--top-n/--limit}"

    echo "--- 상장 리스트·유니버스 스냅샷 커밋 ---"
    if [[ -n "$(git status --porcelain -- stock_data/stock_listing.csv stock_data/mcap_top_200.csv)" ]]; then
        git add stock_data/stock_listing.csv stock_data/mcap_top_200.csv
        git commit -m "auto: mcap_top_200/stock_listing 갱신 ($TERM 재무 적재 전, $(date '+%Y-%m-%d %H:%M'))"
        git push origin main
        echo "git push 완료 (stock_listing/mcap_top_200)"
    else
        echo "상장 리스트/유니버스 변경 없음 — git push 스킵"
    fi

    echo "===== quarterly_financial_update 완료 ($TERM) $(date '+%Y-%m-%d %H:%M:%S') ====="
    echo ">>> 위 A5 오딧 로그를 확인해서 이름 변경·신규 상장 종목이 있으면"
    echo ">>> rename_company_tables.py / backfill_new_listing.py 를 직접 돌릴 것 (자동 실행 안 됨)."
} >> "$LOG_FILE" 2>&1

echo "완료 — 로그: $LOG_FILE"
tail -20 "$LOG_FILE"
