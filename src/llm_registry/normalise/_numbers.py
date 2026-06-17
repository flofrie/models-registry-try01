"""Shared numeric parsers for normalizers."""

import re
from typing import Optional


def parse_size(value: str, unit: str) -> Optional[int]:
    """Parse size notation like 2M, 200K, 30K."""
    try:
        v = float(value)
        u = unit.upper()
        if u == "M":
            return int(v * 1_000_000)
        if u == "K":
            return int(v * 1_000)
        if u == "B":
            return int(v * 1_000_000_000)
        return int(v)
    except (ValueError, TypeError):
        return None


def parse_token_count(cell_text: str) -> Optional[int]:
    """Parse a token count from a spec-table cell."""
    text = cell_text.strip()

    bare = re.match(r"~?([\d,.]+)([KMB])\b", text, re.IGNORECASE)
    if bare:
        return parse_size(bare.group(1).replace(",", ""), bare.group(2))

    m = re.search(r"~?([\d,]+)\s*token", text.replace(",", ""))
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    m = re.search(r"([\d.]+)\s*million", text, re.IGNORECASE)
    if m:
        try:
            return int(float(m.group(1)) * 1_000_000)
        except ValueError:
            pass

    return None
