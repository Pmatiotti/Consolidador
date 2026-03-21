"""Fallback: parseia texto bruto de PDFs Itaú Personnalité.

Usado quando o plugin Itaú detecta o PDF mas as tabelas extraídas são vazias.
O texto bruto das páginas de carteira detalhada contém os dados de posição.
"""

import logging
import re
from typing import List, Optional, Tuple

from models.asset import Asset
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
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
}

# Lines to skip
_SKIP_PATTERNS = (
    "% do cdi", "% do ibovespa", "retorno sobre",
    "% cdi", "total da carteira", "total",
    "produto", "saldo", "aplic", "vencto",
    "taxa contrat", "partic carteira", "risco",
    "sua carteira detalhada", "sua carteira",
)


class ItauTextParser:
    """Parser de texto bruto para Itaú Personnalité.

    Fallback quando plugin Itaú detecta mas tabelas são vazias.
    """

    BROKER = BROKER

    @staticmethod
    def can_handle(text: str) -> bool:
        lower = text.lower()
        has_itau = "itaú" in lower or "itau" in lower or "personnalité" in lower or "personnalite" in lower
        has_carteira = "carteira de investimentos" in lower
        return has_itau and has_carteira

    def extract_from_text(self, full_text: str) -> List[Asset]:
        assets: List[Asset] = []
        lines = full_text.split('\n')

        current_subclasse = "-"
        in_carteira = False

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            lower = line.lower()

            # Detect start of detailed portfolio
            if "sua carteira detalhada" in lower:
                in_carteira = True
                i += 1
                continue

            if not in_carteira:
                i += 1
                continue

            # Detect section headers ("48,8% Juros pós-fixados")
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_section(lower: str) -> Optional[str]:
        """Detect section header like '48,8% Juros pós-fixados'."""
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
        """Asset lines have letters and are not headers."""
        if not line or len(line) < 3:
            return False
        if not re.search(r'[A-Za-z]', line):
            return False
        lower = line.lower()
        if any(lower.startswith(s) for s in _SKIP_PATTERNS):
            return False
        # Pure numbers or percentages
        if re.match(r'^[\d.,\-%]+$', line):
            return False
        return True

    def _extract_asset(self, lines: list, start: int,
                       subclasse: str) -> Tuple[Optional[Asset], int]:
        """Extract asset from text.

        Itaú format in text: asset name may be followed by data on same line
        or on subsequent lines. Data includes: saldo, aplicação date, vencimento,
        taxa, participação, rentabilidades.
        """
        line = lines[start].strip()

        # Try to parse inline data: "NOME R$ xx.xxx,xx dd/mm/aaaa dd/mm/aaaa TAXA ..."
        # or "NOME saldo aplic vencto taxa ..."
        nome = line
        saldo = None
        data_aplic = None
        vencimento = None
        taxa_raw = ""

        # Check if data is inline (line has both text and numbers)
        r_values_inline = re.findall(r'R\$\s*([\d.,]+)', line)
        numbers_inline = re.findall(r'(?<!\S)([\d.,]+)(?!\S)', line)
        dates_inline = re.findall(r'(\d{2}/\d{2}/\d{4})', line)

        consumed = 1

        if r_values_inline:
            # Inline format: extract name before first R$
            first_r = re.search(r'R\$', line)
            if first_r:
                nome = line[:first_r.start()].strip()
            saldo = parse_br(r_values_inline[0])
        else:
            # Data on following lines
            r_values = []
            dates = []

            for j in range(start + 1, min(start + 12, len(lines))):
                next_line = lines[j].strip()
                lower_next = next_line.lower()

                # Stop at next section or asset
                if self._detect_section(lower_next):
                    break
                if self._looks_like_asset(next_line) and (r_values or dates):
                    break
                if self._is_skip_line(lower_next):
                    break

                consumed += 1

                # R$ value
                r_match = re.search(r'R\$\s*([\d.,]+)', next_line)
                if r_match:
                    r_values.append(r_match.group(1))
                    continue

                # Date
                if re.match(r'^\d{2}/\d{2}/\d{4}$', next_line):
                    dates.append(next_line)
                    continue

                # Number (could be saldo without R$ prefix)
                if re.match(r'^[\d.,]+$', next_line):
                    val = parse_br(next_line)
                    if val and val > 100:
                        r_values.append(next_line)
                    continue

                # Taxa
                if re.match(r'^[\d,]+%', next_line) or next_line.lower() in ('cdi', 'ipca'):
                    taxa_raw += " " + next_line
                    continue

            if r_values:
                saldo = parse_br(r_values[0])
            if dates:
                data_aplic = dates[0]
            if len(dates) >= 2:
                vencimento = dates[1]

        if dates_inline:
            data_aplic = dates_inline[0]
            if len(dates_inline) >= 2:
                vencimento = dates_inline[1]

        if not saldo or saldo == 0:
            return None, 1

        # Parse taxa
        indexador, taxa = parse_tax(taxa_raw.strip()) if taxa_raw.strip() else ("-", None)

        tipo_ativo = classify_asset(nome)
        upper_name = nome.upper()

        # Reclassification
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

        # Infer indexador from subclasse if not found
        if indexador == "-" and taxa is None:
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
            data_aplicacao=parse_date(data_aplic) if data_aplic else None,
            indexador=indexador,
            taxa=taxa,
            vencimento=parse_date(vencimento) if vencimento else None,
            liquidez=None,
            valor_aplicado=None,
            valor_bruto=saldo,
            valor_liquido=None,
            classe=classe,
            subclasse=subclasse,
        ), consumed
