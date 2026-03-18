"""Parsing universal de taxas de investimentos brasileiros."""

import re
from typing import Optional, Tuple


def parse_tax(raw: str) -> Tuple[str, Optional[float]]:
    """Converte string de taxa bruta em (indexador, valor_numerico).

    Cobre formatos de BTG, Monte Bravo, XP, Itaú.
    """
    if raw is None:
        return ("-", None)

    cleaned = raw.strip()
    if not cleaned or cleaned == "-":
        return ("-", None)

    # --- Itaú: formato concatenado longo ---

    # "100,0000000%IPCA+7,1" → ("IPCA +", 7.10)
    m = re.match(r'^[\d,]+%\s*IPCA\s*\+\s*([\d,]+)$', cleaned, re.IGNORECASE)
    if m:
        spread = _parse_br_number(m.group(1))
        return ("IPCA +", _round2(spread))

    # "100,0000000%VCP" → ("% VCP", 100.00)
    m = re.match(r'^([\d,]+)%\s*VCP$', cleaned, re.IGNORECASE)
    if m:
        val = _parse_br_number(m.group(1))
        return ("% VCP", _round2(val))

    # "100,0000000%CDI" → ("% CDI", 100.00)
    m = re.match(r'^([\d,]+)%\s*CDI$', cleaned, re.IGNORECASE)
    if m:
        val = _parse_br_number(m.group(1))
        return ("% CDI", _round2(val))

    # "12,90000000000%aa" → ("Prefixado", 12.90) — %aa = prefixado
    m = re.match(r'^([\d,]+)%\s*a\.?a\.?$', cleaned, re.IGNORECASE)
    if m:
        val = _parse_br_number(m.group(1))
        return ("Prefixado", _round2(val))

    # --- BTG ---

    # "16,37% a.a." → ("Prefixado", 16.37)
    m = re.match(r'^([\d,]+)%\s+a\.a\.$', cleaned)
    if m:
        val = _parse_br_number(m.group(1))
        return ("Prefixado", _round2(val))

    # "100% PRE" → ("Alternativo", 100.00)
    m = re.match(r'^([\d,]+)%\s*PRE$', cleaned, re.IGNORECASE)
    if m:
        val = _parse_br_number(m.group(1))
        return ("Alternativo", _round2(val))

    # --- CDI patterns ---

    # "CDI + 0,85%" or "CDI +0,85%" or "CDI - 0,75%" or "CDI -0,75%"
    m = re.match(r'^CDI\s*([+-])\s*([\d,]+)%?$', cleaned, re.IGNORECASE)
    if m:
        sign = -1 if m.group(1) == '-' else 1
        val = _parse_br_number(m.group(2))
        return ("CDI +", _round2(sign * val))

    # "122,00% do CDI" → ("% CDI", 122.00)
    m = re.match(r'^([\d,]+)%\s+do\s+CDI$', cleaned, re.IGNORECASE)
    if m:
        val = _parse_br_number(m.group(1))
        return ("% CDI", _round2(val))

    # "92,00% CDI" or "105,00% CDI" → ("% CDI", ...)
    m = re.match(r'^([\d,]+)%\s+CDI$', cleaned, re.IGNORECASE)
    if m:
        val = _parse_br_number(m.group(1))
        return ("% CDI", _round2(val))

    # --- IPCA / IPC-A patterns ---

    # "IPCA + 8,75%" or "IPC-A + 6,40%" or "IPC-A +7,27%"
    m = re.match(r'^IPC-?A?\s*\+\s*([\d,]+)%?$', cleaned, re.IGNORECASE)
    if m:
        val = _parse_br_number(m.group(1))
        return ("IPCA +", _round2(val))

    # --- Monte Bravo / XP: prefixado ---

    # "+ 13,70%" → ("Prefixado", 13.70)
    m = re.match(r'^\+\s*([\d,]+)%$', cleaned)
    if m:
        val = _parse_br_number(m.group(1))
        return ("Prefixado", _round2(val))

    # Fallback: try to extract a number
    return ("-", None)


def parse_tax_bradesco(compra: str, ano: str) -> Tuple[str, Optional[float]]:
    """Parse taxa Bradesco com 2 colunas: 'Taxa de compra' e 'Taxa ao ano'.

    Exemplos:
        parse_tax_bradesco("IPCA", "8,70%") → ("IPCA +", 8.70)
        parse_tax_bradesco("PRÉ", "11,38%") → ("Prefixado", 11.38)
        parse_tax_bradesco("-", "-")         → ("-", None)
    """
    compra_clean = (compra or "").strip()
    ano_clean = (ano or "").strip()

    if not compra_clean or compra_clean == "-":
        if not ano_clean or ano_clean == "-":
            return ("-", None)

    # Extract numeric value from ano
    val = None
    m = re.match(r'^([\d,]+)%?', ano_clean)
    if m:
        val = _parse_br_number(m.group(1))
        val = _round2(val) if val is not None else None

    compra_upper = compra_clean.upper()

    if "IPCA" in compra_upper or "IPC" in compra_upper:
        return ("IPCA +", val)
    elif "PRÉ" in compra_upper or "PRE" in compra_upper:
        return ("Prefixado", val)
    elif "CDI" in compra_upper:
        if "+" in compra_clean:
            return ("CDI +", val)
        return ("% CDI", val)

    if val is not None:
        return ("Prefixado", val)

    return ("-", None)


def _parse_br_number(s: str) -> Optional[float]:
    """Parse um número brasileiro simples (sem R$, sem pontos de milhar complexos)."""
    cleaned = s.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _round2(val: Optional[float]) -> Optional[float]:
    """Arredonda para 2 casas decimais."""
    if val is None:
        return None
    return round(val, 2)
