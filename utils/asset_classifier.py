"""Classificação de tipo de ativo baseada no nome."""

import re
from typing import Tuple, Optional


def classify_asset(name: str) -> str:
    """Identifica o tipo de ativo baseado no nome (em ordem de prioridade).

    Returns:
        Tipo do ativo: "CDB", "LCA", "LCI", "CRA", "CRI", "DEB", "LIG",
        "LCD", "LF", "NTN-B", "CDCA", "CPR", "COE", "FII", "Previdência",
        "Fundo", "Conta Corrente", ou "Outro".
    """
    upper = name.upper()

    # Ordem de prioridade conforme spec
    if "CDCA" in upper:
        return "CDCA"
    if "CPR" in upper:
        return "CPR"
    if "CRA" in upper:
        return "CRA"
    if "CRI" in upper:
        return "CRI"
    if "CDB" in upper:
        return "CDB"
    if "LCA" in upper:
        return "LCA"
    if "LCI" in upper:
        return "LCI"
    if "LCD" in upper:
        return "LCD"
    if "LIG" in upper:
        return "LIG"
    if re.search(r'\bLF[\s\-]', upper) or upper.endswith("LF"):
        return "LF"
    if "NTN-B" in upper or "NTNB" in upper:
        return "NTN-B"
    if "DEB" in upper or "DEBÊNTURE" in upper or "DEBENTURE" in upper:
        return "DEB"
    if "COE" in upper:
        return "COE"
    if "FII" in upper or "CI(" in upper:
        return "FII"
    if any(k in upper for k in ["PREV", "VGBL", "PGBL", "FLEXPREV"]):
        return "Previdência"
    if any(k in upper for k in ["FIRF", "FIP", "FIDC", "FIC", "FIF", "FIAGRO"]):
        return "Fundo"
    # Bradesco fund names
    if any(k in upper for k in ["BRADESCO DEBÊNTURES", "BRADESCO DEBENTURES",
                                  "BRADESCO PLUS", "BRADESCO BOLSA"]):
        return "Fundo"
    # Itaú fund/COE names
    if any(k in upper for k in ["PRIVILEGE", "GLOBAL DINAM", "ISENTO",
                                  "ITAU DEBENTURES", "ITAU VINLAND", "ITAU ADVANCED"]):
        return "Fundo"
    if any(k in upper for k in ["GANHO GARANTI", "NASDAQ", "SP 500"]):
        return "COE"
    if any(k in upper for k in ["CONTA", "SALDO"]):
        return "Conta Corrente"

    return "Outro"


def classify_classe(tipo_ativo: str) -> str:
    """Determina a classe a partir do tipo de ativo."""
    rf = {"CDB", "LCA", "LCI", "CRA", "CRI", "DEB", "LIG", "LCD", "LF",
          "NTN-B", "CDCA", "CPR"}
    if tipo_ativo in rf:
        return "Renda Fixa"
    if tipo_ativo == "Fundo":
        return "Fundo de Investimento"
    if tipo_ativo == "COE":
        return "COE"
    if tipo_ativo == "Previdência":
        return "Previdência"
    if tipo_ativo == "FII":
        return "Renda Variável"
    if tipo_ativo == "Conta Corrente":
        return "Conta Corrente"
    return "Renda Fixa"
