"""분기 문자열(예: 2023Q1) 파싱·구간 순회. DB 스크립트 공통."""

from __future__ import annotations

from typing import Iterable


def parse_term(term: str) -> tuple[int, int]:
    try:
        year = int(term[:4])
        quarter = int(term[-1])
    except ValueError as exc:
        raise ValueError(f"Invalid term format: {term}") from exc
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"Quarter must be 1..4: {term}")
    return year, quarter


def shift_term(term: str, delta_quarters: int) -> str:
    """분기 문자열을 delta_quarters 만큼 이동 (-1 이면 직전 분기)."""
    y, q = parse_term(term)
    idx = y * 4 + (q - 1) + delta_quarters
    ny, r = divmod(idx, 4)
    return f"{ny}Q{r + 1}"


def iter_terms(start_term: str, end_term: str) -> Iterable[tuple[int, int, str]]:
    sy, sq = parse_term(start_term)
    ey, eq = parse_term(end_term)
    cur_y, cur_q = sy, sq

    while (cur_y < ey) or (cur_y == ey and cur_q <= eq):
        yield cur_y, cur_q, f"{cur_y}Q{cur_q}"
        cur_q += 1
        if cur_q == 5:
            cur_q = 1
            cur_y += 1
