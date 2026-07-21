from __future__ import annotations

import sqlite3
from pathlib import Path
from time import sleep

import pandas as pd

pd.set_option("display.max_rows", 500)
pd.set_option("display.max_columns", 500)

BASE_DIR = Path(__file__).resolve().parent.parent
STOCK_LISTING_PATH = BASE_DIR / "stock_data" / "stock_listing.csv"
FINANCIAL_DB_DIR = BASE_DIR / "data" / "financial_statement"
DIVIDEND_DB_DIR = BASE_DIR / "data" / "dividend"
STOCKS_DB_DIR = BASE_DIR / "data" / "stocks"

# `stock_listing.csv` 의 Market — 일반 파이프라인에서 제외(KONEX·코스닥글로벌 등).
LISTING_EXCLUDED_MARKETS: frozenset[str] = frozenset({"KONEX", "KOSDAQ GLOBAL"})


def _normalize_krx_stock_code(code: object) -> str:
    """OpenDartReader find_corp_code: 6자리 종목코드. CSV가 86790 형태일 때 086790 으로 맞춤."""
    s = str(code).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if s.isdigit() and len(s) <= 6:
        return s.zfill(6)
    return s


def load_listing_dataframe() -> pd.DataFrame:
    """`stock_listing.csv` 전체 행. Code·Name 은 정규화하지 않은 원본에 가깝게."""
    df = pd.read_csv(STOCK_LISTING_PATH)
    if "Code" not in df.columns or "Name" not in df.columns:
        raise ValueError("stock_listing.csv 에 Code, Name 컬럼이 필요합니다.")
    return df


def listing_instrument_exclusion_mask(
    df: pd.DataFrame,
    *,
    check_preferred: bool = True,
    check_spac_name: bool = True,
    check_spac_dept: bool = True,
    check_reit: bool = True,
    check_fund_trust: bool = True,
    check_excluded_markets: bool = True,
) -> pd.Series:
    """
    행 단위 True = DART 분기 DB 적재에서 제외할 종목.
    `Name` 필수, `Dept` 있으면 SPAC 부서 검사에 사용.
    `Market` 이 있으면 `LISTING_EXCLUDED_MARKETS`(KONEX·KOSDAQ GLOBAL 등) 기본 제외.
    """
    nm = df["Name"].astype(str).str.strip()
    ex = pd.Series(False, index=df.index)
    if check_preferred:
        ex |= nm.str.endswith("우") | nm.str.endswith("우B")
    if check_spac_name:
        ex |= nm.str.contains("스팩", na=False)
    if check_reit:
        ex |= nm.str.contains("리츠", na=False)
    if check_fund_trust:
        ex |= nm.str.contains("펀드", na=False)
        ex |= nm.str.contains("신탁", na=False)
    if check_spac_dept and "Dept" in df.columns:
        dept = df["Dept"].astype(str).fillna("")
        ex |= dept.str.contains("SPAC", case=False, na=False)
    if check_excluded_markets and "Market" in df.columns:
        mkt = df["Market"].astype(str).str.strip()
        ex |= mkt.isin(LISTING_EXCLUDED_MARKETS)
    return ex


def listing_pipeline_allowed_names() -> frozenset[str]:
    """
    DART 적재·TTM/분석 파이프라인 공통 허용 종목명 집합.
    우선주·스팩·리츠·펀드·신탁·SPAC(부)·KONEX·KOSDAQ GLOBAL 제외 (`listing_instrument_exclusion_mask` 와 동일).
    """
    cdf = load_listing_dataframe().copy()
    cdf["Name"] = cdf["Name"].astype(str).str.strip()
    keep = ~listing_instrument_exclusion_mask(cdf)
    return frozenset(cdf.loc[keep, "Name"].unique())


def load_company_names_frozenset(path: Path | None) -> frozenset[str] | None:
    """
    한 줄에 하나씩 종목명(stock_listing.csv 의 Name 과 동일).
    빈 줄·# 으로 시작하는 줄은 무시.
    """
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"company names file not found: {p}")
    names: set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        names.add(s)
    return frozenset(names)


def listing_names_ordered_by_marcap(
    *,
    market: str | None = None,
    exclude_spac: bool = True,
    exclude_preferred: bool = True,
    exclude_reit: bool = True,
    exclude_fund_trust: bool = True,
    exclude_spac_dept: bool = True,
    exclude_markets: bool = True,
) -> list[str]:
    """
    `stock_listing.csv` 를 시총(Marcap) 내림차순으로 본 Name 목록.
    동일 Name 은 첫 행(시총 큰 쪽)만 유지.

    기본: 우선주·이름 스팩·리츠·펀드·신탁·Dept SPAC·`LISTING_EXCLUDED_MARKETS` 행 제외.
    """
    df = load_listing_dataframe()
    if "Marcap" not in df.columns:
        raise ValueError("stock_listing.csv 에 Marcap 컬럼이 필요합니다.")
    work = df.copy()
    if market and "Market" in work.columns:
        work = work[work["Market"].astype(str) == market]
    nm = work["Name"].astype(str).str.strip()
    work = work.assign(_nm=nm)
    ok = work["_nm"].notna() & (work["_nm"] != "") & (work["_nm"] != "nan")
    work = work.loc[ok]
    tmp = work.assign(Name=work["_nm"])
    ex = listing_instrument_exclusion_mask(
        tmp,
        check_preferred=exclude_preferred,
        check_spac_name=exclude_spac,
        check_spac_dept=exclude_spac_dept,
        check_reit=exclude_reit,
        check_fund_trust=exclude_fund_trust,
        check_excluded_markets=exclude_markets,
    )
    work = work.loc[~ex]
    work = work.assign(Marcap=pd.to_numeric(work["Marcap"], errors="coerce"))
    work = work.sort_values("Marcap", ascending=False, na_position="last")
    seen: set[str] = set()
    out: list[str] = []
    for name in work["_nm"]:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def company_names_top_n_by_marcap(n: int) -> frozenset[str]:
    """시총 순 상위 n개. 우선주·스팩·리츠·펀드·신탁·SPAC(부)·KONEX·KOSDAQ GLOBAL 제외 후 시총 순 (`--top-n`)."""
    if n < 1:
        raise ValueError("n must be >= 1")
    ordered = listing_names_ordered_by_marcap(market=None)
    return frozenset(ordered[:n])


def mcap_top_n_listing_rows(n: int) -> pd.DataFrame:
    """
    시총(Marcap) 내림차순 상위 n행. `listing_names_ordered_by_marcap` 과 동일 필터·Name 중복 시 첫 행만 유지.
    컬럼: rank(1..n), Code, Name, Marcap, (있으면) Market
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    df = load_listing_dataframe()
    if "Marcap" not in df.columns or "Code" not in df.columns:
        raise ValueError("stock_listing.csv 에 Marcap, Code 컬럼이 필요합니다.")
    work = df.copy()
    nm = work["Name"].astype(str).str.strip()
    work = work.assign(_nm=nm)
    ok = work["_nm"].notna() & (work["_nm"] != "") & (work["_nm"] != "nan")
    work = work.loc[ok]
    tmp = work.assign(Name=work["_nm"])
    ex = listing_instrument_exclusion_mask(tmp)
    work = work.loc[~ex]
    work = work.assign(Marcap=pd.to_numeric(work["Marcap"], errors="coerce"))
    work = work.sort_values("Marcap", ascending=False, na_position="last")
    work = work.drop_duplicates(subset=["_nm"], keep="first")
    work = work.head(n).reset_index(drop=True)
    out = pd.DataFrame(
        {
            "rank": range(1, len(work) + 1),
            "Code": work["Code"].astype(str).str.replace(r"\.0$", "", regex=True),
            "Name": work["_nm"].values,
            "Marcap": work["Marcap"].values,
        }
    )
    if "Market" in work.columns:
        out["Market"] = work["Market"].astype(str).values
    return out


class FS_DB:
    """로컬 SQLite 읽기는 OpenDartReader 없이 동작. DART API는 첫 호출 시에만 로드."""

    def __init__(self):
        self._dart = None

    @property
    def dart(self):
        if self._dart is None:
            import OpenDartReader
            from scripts.config import get_dart_api_key

            self._dart = OpenDartReader(get_dart_api_key())
        return self._dart

    def _dart_corp_arg(self, code: object, name: str | None = None) -> str:
        """
        OpenDartReader 가 받는 corp 인자(종목코드 또는 정확 회사명).
        종목코드가 DART 고유번호 캐시에 없으면 stock_listing 의 Name 으로 재시도
        (예: 0126Z0 등 비표준 코드 → 삼성에피스홀딩스).
        """
        dart = self.dart
        code_s = _normalize_krx_stock_code(code)
        if dart.find_corp_code(code_s):
            return code_s
        if name is not None:
            nm = str(name).strip()
            if nm and nm != "nan" and dart.find_corp_code(nm):
                return nm
        return code_s

    def stock_listing(self):
        import FinanceDataReader as fdr

        sm = fdr.DataReader("005930")
        print(sm)
        stocks = fdr.StockListing("KRX")
        stocks.to_csv("stock_listing_1.csv", index=False)
        print(stocks)

    def finstate_data(
        self, code, year, quater, name: str | None = None, *, verbose: bool = True
    ):
        if quater == 1:
            reprt = "11013"
        elif quater == 2:
            reprt = "11012"
        elif quater == 3:
            reprt = "11014"
        elif quater == 4:
            reprt = "11011"
        else:
            raise ValueError(f"invalid quarter: {quater}")
        code_s = _normalize_krx_stock_code(code)
        corp = self._dart_corp_arg(code, name)
        if verbose and corp != code_s:
            print("  (DART: 종목코드 미매칭 → 회사명으로 재무 조회)")
        dart = self.dart
        df = dart.finstate_all(corp, year, reprt, fs_div="CFS")
        if df is not None and not df.empty:
            return df
        df_o = dart.finstate_all(corp, year, reprt, fs_div="OFS")
        if verbose and df_o is not None and not df_o.empty:
            print("  (연결 CFS 비어 있음 → 별도 OFS 로 재조회)")
        return df_o if df_o is not None else pd.DataFrame()

    def dividend_data(
        self, code, year, quater, name: str | None = None, *, verbose: bool = True
    ):
        if quater == 1:
            quater = "11013"
        elif quater == 2:
            quater = "11012"
        elif quater == 3:
            quater = "11014"
        elif quater == 4:
            quater = "11011"
        code_s = _normalize_krx_stock_code(code)
        corp = self._dart_corp_arg(code, name)
        if verbose and corp != code_s:
            print("  (DART: 종목코드 미매칭 → 회사명으로 배당 조회)")
        return self.dart.report(corp, "배당", year, quater)

    def stock_data(
        self, code, year, quater, name: str | None = None, *, verbose: bool = True
    ):
        if quater == 1:
            quater = "11013"
        elif quater == 2:
            quater = "11012"
        elif quater == 3:
            quater = "11014"
        elif quater == 4:
            quater = "11011"
        code_s = _normalize_krx_stock_code(code)
        corp = self._dart_corp_arg(code, name)
        if verbose and corp != code_s:
            print("  (DART: 종목코드 미매칭 → 회사명으로 주식총수 조회)")
        return self.dart.report(corp, "주식총수", year, quater)

    @staticmethod
    def listing_code_name_pairs(
        company_names: frozenset[str] | None = None,
        *,
        apply_listing_exclusions: bool = True,
    ) -> list[tuple[str, str]]:
        cdf = load_listing_dataframe().copy()
        cdf["Code"] = cdf["Code"].map(_normalize_krx_stock_code)
        cdf["Name"] = cdf["Name"].astype(str).str.strip()
        if company_names is not None:
            cdf = cdf[cdf["Name"].isin(company_names)]
        elif apply_listing_exclusions:
            cdf = cdf.loc[~listing_instrument_exclusion_mask(cdf)]
        return list(zip(cdf["Code"].tolist(), cdf["Name"].tolist()))

    def create_finstate_db(
        self,
        year,
        quater,
        company_names: frozenset[str] | None = None,
        *,
        apply_listing_exclusions: bool = True,
    ):
        pairs = self.listing_code_name_pairs(
            company_names,
            apply_listing_exclusions=apply_listing_exclusions,
        )
        term = f"{year}Q{quater}"
        if not pairs:
            print(f"{term} 재무: 적재할 종목이 없습니다 (필터 또는 리스트 확인).")
            return
        con = sqlite3.connect(FINANCIAL_DB_DIR / f"{term}.db")
        print(f"{term} DB 를 연결했습니다. (종목 {len(pairs)}개)")
        for i, (code, name) in enumerate(pairs):
            print(i, "번째")
            try:
                print(f"{name} 데이터를 조회합니다.")
                data = self.finstate_data(code, year, quater, name=name)
                if data is not None and not data.empty:
                    data.to_sql(f"{name}", con, if_exists="replace")
                    print(f"{name} 테이블이 완성되었습니다.")
                else:
                    print(
                        f"{name}: 조회 결과 없음(CFS·OFS 모두 비어 있음) — "
                        f"기존 테이블이 있으면 덮어쓰지 않음"
                    )
                print()
                sleep(2)
            except Exception:
                print(f"{name} 데이터는 없습니다.")
                print()
                sleep(2)
        con.commit()
        con.close()

    def create_dividend_db(
        self,
        year,
        quater,
        company_names: frozenset[str] | None = None,
        *,
        apply_listing_exclusions: bool = True,
    ):
        pairs = self.listing_code_name_pairs(
            company_names,
            apply_listing_exclusions=apply_listing_exclusions,
        )
        term = f"{year}Q{quater}"
        if not pairs:
            print(f"{term} 배당: 적재할 종목이 없습니다 (필터 또는 리스트 확인).")
            return
        con = sqlite3.connect(DIVIDEND_DB_DIR / f"{term}.db")
        print(f"{term} DB 를 연결했습니다. (종목 {len(pairs)}개)")
        for i, (code, name) in enumerate(pairs):
            print(i, "번째")
            try:
                print(f"{name} 데이터를 조회합니다.")
                data = self.dividend_data(code, year, quater, name=name)
                if isinstance(data, pd.DataFrame) and not data.empty:
                    data.to_sql(f"{name}", con, if_exists="replace")
                    print(f"{name} 테이블이 완성되었습니다.")
                else:
                    print(
                        f"{name}: 배당 조회 결과 없음 — "
                        f"기존 테이블이 있으면 덮어쓰지 않음"
                    )
                print()
                sleep(2)
            except Exception:
                print(f"{name} 데이터는 없습니다.")
                print()
                sleep(2)
        con.commit()
        con.close()

    def create_stock_db(
        self,
        year,
        quater,
        company_names: frozenset[str] | None = None,
        *,
        apply_listing_exclusions: bool = True,
    ):
        pairs = self.listing_code_name_pairs(
            company_names,
            apply_listing_exclusions=apply_listing_exclusions,
        )
        term = f"{year}Q{quater}"
        if not pairs:
            print(f"{term} 주식: 적재할 종목이 없습니다 (필터 또는 리스트 확인).")
            return
        con = sqlite3.connect(STOCKS_DB_DIR / f"{term}.db")
        print(f"{term} DB 를 연결했습니다. (종목 {len(pairs)}개)")
        for i, (code, name) in enumerate(pairs):
            print(i, "번째")
            try:
                print(f"{name} 데이터를 조회합니다.")
                data = self.stock_data(code, year, quater, name=name)
                if isinstance(data, pd.DataFrame) and not data.empty:
                    data.to_sql(f"{name}", con, if_exists="replace")
                    print(f"{name} 테이블이 완성되었습니다.")
                else:
                    print(
                        f"{name}: 주식총수 조회 결과 없음(DART 응답 비어 있음·status 오류 등) — "
                        f"기존 테이블이 있으면 덮어쓰지 않음"
                    )
                print()
                sleep(2)
            except Exception as e:
                print(f"{name} 주식 DB 적재 실패: {e!r}")
                print()
                sleep(2)
        con.commit()
        con.close()

    def read_dividend_db(self, term, company):
        con = sqlite3.connect(DIVIDEND_DB_DIR / f"{term}.db")
        df = pd.read_sql(f"SELECT * FROM '{company}'", con).drop(columns=["index"])
        con.close()
        return df

    def read_fs_db(self, term, company):
        con = sqlite3.connect(FINANCIAL_DB_DIR / f"{term}.db")
        df = pd.read_sql(f"SELECT * FROM '{company}'", con).drop(columns=["index"])
        con.close()
        return df

    def read_stock_db(self, term, company):
        con = sqlite3.connect(STOCKS_DB_DIR / f"{term}.db")
        df = pd.read_sql(f"SELECT * FROM '{company}'", con).drop(columns=["index"])
        con.close()
        return df
