"""텍스트 수동 리스트 로딩 — 분류 DB와 무관 (루트 `stock_data/` 데이터 디렉터리와 별개)."""

from __future__ import annotations

from pathlib import Path


def load_cyclical_manual_universe(path: Path) -> list[str]:
    """
    `cyclical_manual_universe.txt` 단일 파일.
    - 편입: 비어 있지 않은 줄, `#` 아님, `-` 로 시작하지 않음. 선택 접두사 `+`.
    - 제외: `- 이름` (하이픈 뒤 공백·이름).
    순서는 파일에서 편입이 처음 나온 순서, 마지막에 제외 집합을 빼서 확정.
    """
    if not path.is_file():
        return []
    excluded: set[str] = set()
    order: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("-"):
            name = raw[1:].strip()
            if name:
                excluded.add(name)
            continue
        if raw.startswith("+"):
            raw = raw[1:].strip()
        if not raw:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        order.append(raw)
    return [n for n in order if n not in excluded]


def load_name_set(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        names.append(s)
    return frozenset(names)


def load_keep_ordered(path: Path) -> list[str]:
    """파일 순서 유지, 중복 제거."""
    if not path.is_file():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out
