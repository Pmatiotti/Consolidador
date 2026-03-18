"""Parsing de números no formato brasileiro (vírgula decimal, ponto milhares)."""

import re
from typing import Optional


def parse_br(value: str) -> Optional[float]:
    """Converte string numérica brasileira para float.

    Trata: prefixo 'R$', espaços, setas unicode, strings vazias, '-'.

    Exemplos:
        parse_br("1.247.126,85") → 1247126.85
        parse_br("R$ 50.539,60") → 50539.60
        parse_br("-")            → None
    """
    if value is None:
        return None

    # Remove espaços, R$, setas unicode
    cleaned = value.strip()
    cleaned = cleaned.replace("R$", "").strip()
    cleaned = re.sub(r'[↑↓\u2191\u2193]', '', cleaned).strip()

    if not cleaned or cleaned == "-":
        return None

    # Remove pontos de milhar, troca vírgula por ponto decimal
    cleaned = cleaned.replace(".", "").replace(",", ".")

    try:
        return float(cleaned)
    except ValueError:
        return None
