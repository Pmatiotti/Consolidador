"""Fallback: parseia texto bruto de PDFs Itaú Personnalité.

Usado quando o plugin Itaú detecta o PDF mas extrai 0 ativos.
Tenta re-extrair tabelas do PDF como último recurso.
"""

import logging
import re
from typing import List, Optional

from models.asset import Asset
from utils.asset_classifier import classify_asset, classify_classe
from utils.number_parser import parse_br
from utils.tax_parser import parse_tax

logger = logging.getLogger(__name__)

BROKER = "Itaú"

# Mapeamento subclasse Itaú → padrão
_SUBCLASSE_MAP = {
    "juros pós-fixados": "Pós-fixado",
    "juros pos-fixados": "Pós-fixado",
    "juros pós fixados": "Pós-fixado",
    "pós-fixados": "Pós-fixado",
    "juros prefixados": "Pré-fixado",
    "prefixados": "Pré-fixado",
    "inflação": "Inflação",
    "inflacao": "Inflação",
    "multimercados": "Multimercado",
    "multimercado": "Multimercado",
    "ações": "Renda Variável",
    "acoes": "Renda Variável",
    "previdência": "Previdência",
    "previdencia": "Previdência",
}

# Lines to skip
_SKIP_PATTERNS = (
    "% do cdi", "% do ibovespa", "retorno sobre",
    "% cdi", "total da carteira", "total",
    "produto", "saldo", "aplic", "vencto",
    "taxa contrat", "partic carteira", "risco",
    "sua carteira detalhada", "sua carteira",
)

# Single-word garbage labels (risk levels, time periods, etc.)
_GARBAGE_WORDS = {
    "alto", "médio", "medio", "baixo", "moderado",
    "meses", "mês", "mes", "anos", "ano",
    "sim", "não", "nao",
    "d+0", "d+1", "d+2", "d+30", "d+31",
    "diário", "diario", "mensal", "anual",
    "risco", "liquidez", "resgate",
}


class ItauTextParser:
    """Parser de texto bruto para Itaú Personnalité.

    Fallback quando plugin Itaú detecta mas tabelas são insuficientes.
    Parseia blocos de texto para extrair nomes de ativos e saldos.
    """

    BROKER = BROKER

    @staticmethod
    def can_handle(text: str) -> bool:
        lower = text.lower()
        has_itau = "itaú" in lower or "itau" in lower or "personnalité" in lower or "personnalite" in lower
        has_carteira = "carteira de investimentos" in lower
        return has_itau and has_carteira

    def extract_from_text(self, full_text: str) -> List[Asset]:
        """Extract assets from raw text.

        Looks for lines with asset names followed by R$ values or large numbers.
        """
        assets: List[Asset] = []
        lines = full_text.split('\n')

        current_subclasse = "-"
        in_carteira = False

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            lower = line.lower()

            # Hard stop: enter footnotes/glossary section — no more asset data
            if "notas explicativas" in lower or lower.startswith("administrador:"):
                break

            # Detect start of detailed portfolio (explicit header or section header
            # immediately followed by a large section-total number)
            if "sua carteira detalhada" in lower:
                in_carteira = True
                i += 1
                continue

            if not in_carteira:
                # Also trigger when a known section header is followed by a big total
                # (e.g. "Juros pós-fixados" / "1.731.567,70" on the first data page).
                # The FIRST section's subclasse is set by this first header.
                section_sub = self._detect_section(lower)
                if section_sub and i + 1 < len(lines):
                    next_val = parse_br(lines[i + 1].strip())
                    if next_val and next_val > 10000:
                        in_carteira = True
                        current_subclasse = section_sub
                        i += 2  # skip first section header + its total
                        # Skip any additional consecutive section-header+total pairs
                        # so that the first actual subclasse is preserved for the
                        # assets that follow immediately.
                        while i < len(lines):
                            lx = lines[i].strip().lower()
                            sub_x = self._detect_section(lx)
                            if sub_x and i + 1 < len(lines):
                                nx_val = parse_br(lines[i + 1].strip())
                                if nx_val and nx_val > 10000:
                                    i += 2  # skip this header+total too
                                    continue
                            break
                        continue
                i += 1
                continue

            # Detect section headers
            section_sub = self._detect_section(lower)
            if section_sub:
                current_subclasse = section_sub
                i += 1
                continue

            # Skip known non-asset lines
            if self._is_skip_line(lower):
                i += 1
                continue

            # Skip empty lines
            if not line:
                i += 1
                continue

            # Try to detect an asset line
            if self._looks_like_asset(line):
                asset, consumed = self._extract_asset(lines, i, current_subclasse)
                if asset:
                    assets.append(asset)
                    i += consumed
                    continue

            i += 1

        return assets

    @staticmethod
    def _detect_section(lower: str) -> Optional[str]:
        for key, val in _SUBCLASSE_MAP.items():
            if key in lower:
                return val
        return None

    @staticmethod
    def _is_skip_line(lower: str) -> bool:
        for pattern in _SKIP_PATTERNS:
            if lower.startswith(pattern):
                return True
        return False

    @staticmethod
    def _looks_like_asset(line: str) -> bool:
        if not line or len(line) < 3:
            return False
        if not re.search(r'[A-Za-z]', line):
            return False
        lower = line.lower().strip()
        if any(lower.startswith(s) for s in _SKIP_PATTERNS):
            return False
        if re.match(r'^[\d.,\-%]+$', line):
            return False
        # Filter single-word garbage labels
        if lower in _GARBAGE_WORDS:
            return False
        # Filter fragment patterns
        if re.match(r'^(de |do |da |dos |das |um |uma |no |na |em |e |a )', lower):
            return False
        # Filter pure date or percentage lines
        if re.match(r'^\d{2}/\d{2}/\d{2,4}', line):
            return False
        # Filter month/year abbreviation like "Fev/26", "Jan/25"
        if re.match(r'^[A-Za-z]{3}/\d{2}', line):
            return False
        # Filter "N meses" / "N anos" patterns like "12 meses", "2 anos"
        if re.match(r'^\d+\s+(mes|mês|ano)', lower):
            return False
        # Filter disclaimer/sentence fragments starting with common Portuguese words
        if re.match(r'^(mínimo|minimo|milhões|milhoes|para o|de acordo|conforme|durante|exceto|sendo|prazo)', lower):
            return False
        return True

    def _extract_asset(self, lines: list, start: int,
                       subclasse: str):
        """Extract asset from text block."""
        line = lines[start].strip()
        nome = line
        saldo = None
        consumed = 1

        # Check for R$ values inline
        r_values_inline = re.findall(r'R\$\s*([\d.,]+)', line)

        if r_values_inline:
            first_r = re.search(r'R\$', line)
            if first_r:
                nome = line[:first_r.start()].strip()
            saldo = parse_br(r_values_inline[0])
        else:
            # Look at following lines for numeric values
            for j in range(start + 1, min(start + 8, len(lines))):
                next_line = lines[j].strip()
                lower_next = next_line.lower()

                if self._detect_section(lower_next):
                    break
                if self._looks_like_asset(next_line) and saldo:
                    break
                if self._is_skip_line(lower_next):
                    break

                consumed += 1

                r_match = re.search(r'R\$\s*([\d.,]+)', next_line)
                if r_match and not saldo:
                    saldo = parse_br(r_match.group(1))
                    continue

                if re.match(r'^[\d.,]+$', next_line) and not saldo:
                    val = parse_br(next_line)
                    if val and val > 100:
                        saldo = val
                    continue

        if not saldo or saldo == 0:
            return None, 1

        tipo_ativo = classify_asset(nome)
        upper_name = nome.upper()

        if any(k in upper_name for k in ["GANHO GARANTI", "NASDAQ", "SP 500"]):
            tipo_ativo = "COE"
            classe = "COE"
            subclasse = "Alternativo"
        elif tipo_ativo == "FII":
            classe = "Renda Variável"
            subclasse = "Renda Variável"
        elif tipo_ativo == "Previdência":
            classe = "Previdência"
            subclasse = "Previdência PGBL" if "PGBL" in upper_name else "Previdência VGBL"
        elif tipo_ativo == "Fundo":
            classe = "Fundo de Investimento"
        elif tipo_ativo == "Outro":
            tipo_ativo = "CDB"
            classe = "Renda Fixa"
        else:
            classe = classify_classe(tipo_ativo)

        indexador = "-"
        if subclasse == "Pós-fixado":
            indexador = "% CDI"
        elif subclasse == "Pré-fixado":
            indexador = "Prefixado"
        elif subclasse == "Inflação":
            indexador = "IPCA +"

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo=tipo_ativo,
            data_aplicacao=None,
            indexador=indexador,
            taxa=None,
            vencimento=None,
            liquidez=None,
            valor_aplicado=None,
            valor_bruto=saldo,
            valor_liquido=None,
            classe=classe,
            subclasse=subclasse,
        ), consumed
