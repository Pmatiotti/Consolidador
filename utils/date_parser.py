"""Parsing de datas DD/MM/AA → DD/MM/AAAA."""

import re
from typing import Optional


def parse_date(value: str) -> Optional[str]:
    """Converte data para formato DD/MM/AAAA.

    - Datas completas passam direto
    - Datas com ano de 2 dígitos: < 50 → 2000+, >= 50 → 1900+

    Exemplos:
        parse_date("22/07/2024") → "22/07/2024"
        parse_date("26/01/26")   → "26/01/2026"
        parse_date("20/08/71")   → "20/08/1971"
        parse_date("-")          → None
    """
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned or cleaned == "-":
        return None

    # DD/MM/AAAA - já completa
    match = re.match(r'^(\d{2}/\d{2}/\d{4})$', cleaned)
    if match:
        return match.group(1)

    # DD/MM/AA - ano curto
    match = re.match(r'^(\d{2}/\d{2})/(\d{2})$', cleaned)
    if match:
        prefix = match.group(1)
        year_short = int(match.group(2))
        year_full = 2000 + year_short if year_short < 50 else 1900 + year_short
        return f"{prefix}/{year_full}"

    return cleaned
