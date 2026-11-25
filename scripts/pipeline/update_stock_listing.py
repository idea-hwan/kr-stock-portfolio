from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

import FinanceDataReader as fdr
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent.parent
STOCK_DATA_DIR = BASE_DIR / "stock_data"
TARGET_PATH = STOCK_DATA_DIR / "stock_listing.csv"
BACKUP_DIR = STOCK_DATA_DIR / "backups"
NEW_CODES_PATH = STOCK_DATA_DIR / "new_codes_since_stock_csv.txt"


def _normalize_listing(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only columns used by this project and align names with the
    existing stock_listing.csv format.
    """
    rename_map = {"Symbol": "Code"}
    df = df.rename(columns=rename_map)

    preferred_cols = [
        "Code",
        "ISU_CD",
        "Name",
        "Market",
        "Dept",
        "Close",
        "ChangeCode",
        "Changes",
        "ChagesRatio",
        "Open",
        "High",
        "Low",
        "Volume",
        "Amount",
        "Marcap",
        "Stocks",
        "MarketId",
    ]
    existing_cols = [c for c in preferred_cols if c in df.columns]
    normalized = df[existing_cols].copy()
    return normalized


def backup_current_file() -> Path | None:
    if not TARGET_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"stock_listing_{ts}.csv"
    shutil.copy2(TARGET_PATH, backup_path)
    return backup_path


def restore_backup(backup_path: Path) -> None:
    if backup_path.exists():
        shutil.copy2(backup_path, TARGET_PATH)


def record_new_codes(added: list[str]) -> int:
    """신규 코드를 new_codes_since_stock_csv.txt 에 누적(dedup) — A4(backfill_new_listing.py)
    입력 파일. 실제 백필 실행은 사람이 판단해서 수동으로 한다(자동 실행 안 함)."""
    if not added:
        return 0
    existing: set[str] = set()
    if NEW_CODES_PATH.exists():
        existing = {
            line.strip()
            for line in NEW_CODES_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    merged = sorted(existing | set(added))
    NEW_CODES_PATH.write_text("\n".join(merged) + "\n", encoding="utf-8")
    return len(merged)


def update_stock_listing() -> None:
    print("Fetching latest KRX listing from FinanceDataReader...")
    latest_raw = fdr.StockListing("KRX")
    latest = _normalize_listing(latest_raw)

    # 2026-11-16·11-23: FinanceDataReader 캐시(2026-11-21)가 시총·종가를 비운 채로
    # 내려왔고, 그 파일을 그대로 저장한 뒤 시총 정렬이 코드 순으로 무너져
    # 상위 200에서 삼성전자가 빠졌다. 시총이 하나도 없으면 기존 파일을 유지한다.
    marcap_ok = (
        "Marcap" in latest.columns
        and pd.to_numeric(latest["Marcap"], errors="coerce").notna().sum() > 0
    )
    if not marcap_ok:
        raise RuntimeError(
            "KRX 리스트에 시가총액이 없습니다. stock_listing.csv 는 덮어쓰지 않습니다."
        )

    old_df = pd.read_csv(TARGET_PATH) if TARGET_PATH.exists() else pd.DataFrame()
    old_count = len(old_df)
    new_count = len(latest)

    old_codes = set(old_df["Code"].astype(str)) if "Code" in old_df.columns else set()
    new_codes = set(latest["Code"].astype(str)) if "Code" in latest.columns else set()
    added = sorted(new_codes - old_codes)
    removed = sorted(old_codes - new_codes)

    backup_path = backup_current_file()
    try:
        latest.to_csv(TARGET_PATH, index=False)
    except Exception:
        if backup_path is not None:
            restore_backup(backup_path)
        raise

    print("Update complete.")
    if backup_path is not None:
        print(f"- backup: {backup_path}")
    print(f"- output: {TARGET_PATH}")
    print(f"- rows: {old_count} -> {new_count}")
    print(f"- added codes: {len(added)}")
    print(f"- removed codes: {len(removed)}")
    if added:
        print("  sample added:", ", ".join(added[:10]))
    if removed:
        print("  sample removed:", ", ".join(removed[:10]))

    if old_codes:
        total_pending = record_new_codes(added)
        if added:
            print(
                f">>> {NEW_CODES_PATH.name} 에 신규 코드 {len(added)}개 추가 "
                f"(누적 대기 {total_pending}개) — 필요하면 backfill_new_listing.py 직접 실행 (자동 실행 안 됨)"
            )
    elif added:
        print(
            f"- (최초 실행이라 {NEW_CODES_PATH.name} 기록 생략 — 전 종목이 added로 잡히는 걸 방지)"
        )


if __name__ == "__main__":
    update_stock_listing()
