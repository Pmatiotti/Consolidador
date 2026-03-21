"""Fallback: parseia texto bruto do Book de Investimentos ONE/BTG.

Diferente do "Relatório de Performance" do BTG. Este é o "Book de Investimentos"
enviado pelo assessor ONE, com layout diferente.
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

BROKER = "BTG Pactual"

# Section markers
_SECTION_MAP = {
    "crédito privado": ("Renda Fixa", "Pós-fixado"),
    "credito privado": ("Renda Fixa", "Pós-fixado"),
    "renda fixa": ("Renda Fixa", "Pós-fixado"),
    "pós-fixado": ("Renda Fixa", "Pós-fixado"),
    "pos-fixado": ("Renda Fixa", "Pós-fixado"),
    "pré-fixado": ("Renda Fixa", "Pré-fixado"),
    "pre-fixado": ("Renda Fixa", "Pré-fixado"),
    "inflação": ("Renda Fixa", "Inflação"),
    "inflacao": ("Renda Fixa", "Inflação"),
    "fundo de investimento": ("Fundo de Investimento", "Multimercado"),
    "fundos de investimento": ("Fundo de Investimento", "Multimercado"),
    "renda variável": ("Renda Variável", "Renda Variável"),
    "renda variavel": ("Renda Variável", "Renda Variável"),
    "previdência": ("Previdência", "Previdência VGBL"),
    "previdencia": ("Previdência", "Previdência VGBL"),
    "coe": ("COE", "Alternativo"),
}

# Stop markers
_STOP_MARKERS = (
    "rentabilidade", "movimentação", "movimentacao",
    "disclaimer", "importante", "assessor",
    "total da carteira", "patrimônio", "patrimonio",
)

# Header lines to skip
_HEADER_KEYWORDS = (
    "produto", "data de contratação", "data de contratacao",
    "saldo bruto", "valor disp", "valor investido",
    "rentabilidade", "data de vencimento", "vencimento",
)


class ONEBookTextParser:
    """Parser de texto bruto para Book de Investimentos ONE/BTG.

    Fallback quando o PDF é o formato "Book" (não "Relatório de Performance").
    """

    BROKER = BROKER

    @staticmethod
    def can_handle(text: str) -> bool:
        lower = text.lower()
        has_book = "book de investimentos" in lower or "book de investimento" in lower
        has_one = "one" in lower or "luis fernando" in lower
        # Must not be handled by BTG performance parser
        has_performance = "relatório de performance" in lower
        return has_book and has_one and not has_performance

    def extract_from_text(self, full_text: str) -> List[Asset]:
        assets: List[Asset] = []
        lines = full_text.split('\n')

        current_classe = ""
        current_subclasse = "-"
        in_position = False

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            lower = line.lower()

            # Stop markers
            if any(lower.startswith(m) for m in _STOP_MARKERS):
                i += 1
                continue

            # Section detection
            section = self._detect_section(lower)
            if section:
                current_classe, current_subclasse = section
                in_position = True
                i += 1
                continue

            # Skip header lines
            if self._is_header_line(lower):
                i += 1
                continue

            # Skip empty
            if not line:
                i += 1
                continue

            # Try asset detection
            if in_position and self._looks_like_asset(line):
                asset, consumed = self._extract_asset(
                    lines, i, current_classe, current_subclasse
                )
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
    def _detect_section(lower: str) -> Optional[Tuple[str, str]]:
        for key, val in _SECTION_MAP.items():
            if key in lower:
                return val
        return None

    @staticmethod
    def _is_header_line(lower: str) -> bool:
        return any(lower.startswith(h) for h in _HEADER_KEYWORDS)

    @staticmethod
    def _looks_like_asset(line: str) -> bool:
        if not line or len(line) < 3:
            return False
        if not re.search(r'[A-Za-z]', line):
            return False
        if line.startswith('R$') or line == '-':
            return False
        if re.match(r'^\d{2}/\d{2}/\d{4}$', line):
            return False
        if re.match(r'^[\d.,]+%?$', line):
            return False
        upper = line.upper()
        skip = ("TOTAL", "SUBTOTAL", "PRODUTO", "DATA DE", "SALDO",
                "VALOR", "RENTABILIDADE", "VENCIMENTO")
        return not any(upper.startswith(s) for s in skip)

    def _extract_asset(self, lines: list, start: int,
                       classe: str, subclasse: str) -> Tuple[Optional[Asset], int]:
        """Extract asset from ONE Book text.

        Book format columns:
        Produto | Data de Contratação | Saldo Bruto (R$) | Valor Disp. para Resgate |
        Valor Investido | Rentabilidade Mês | Rentabilidade 12 Meses | Data de Vencimento
        """
        nome = lines[start].strip()
        dates = []
        r_values = []
        numbers = []
        consumed = 1

        for j in range(start + 1, min(start + 15, len(lines))):
            next_line = lines[j].strip()
            lower_next = next_line.lower()

            # Stop at next section, stop marker, or next asset
            if self._detect_section(lower_next):
                break
            if any(lower_next.startswith(m) for m in _STOP_MARKERS):
                break
            if self._is_header_line(lower_next):
                consumed += 1
                continue
            if self._looks_like_asset(next_line) and (r_values or numbers):
                break

            consumed += 1

            # Date
            if re.match(r'^\d{2}/\d{2}/\d{4}$', next_line):
                dates.append(next_line)
                continue

            # R$ value
            r_match = re.search(r'R\$\s*([\d.,]+)', next_line)
            if r_match:
                r_values.append(r_match.group(1))
                continue

            # Pure number
            if re.match(r'^[\d.,]+$', next_line):
                val = parse_br(next_line)
                if val is not None:
                    numbers.append(next_line)
                continue

            # Percentage — skip
            if re.match(r'^-?[\d.,]+%$', next_line):
                continue

            # Dash — skip
            if next_line == '-':
                continue

            # Additional name line (if no data yet)
            if not r_values and not numbers and re.search(r'[A-Za-z]', next_line):
                nome += " " + next_line
                continue

        # Combine R$ values and plain numbers
        all_values = r_values + numbers

        if not all_values:
            return None, 1

        # Map values: Saldo Bruto, Valor Disp. Resgate (líquido), Valor Investido
        saldo_bruto = parse_br(all_values[0])
        saldo_liquido = parse_br(all_values[1]) if len(all_values) >= 2 else None
        valor_investido = parse_br(all_values[2]) if len(all_values) >= 3 else None

        if not saldo_bruto or saldo_bruto == 0:
            return None, consumed

        data_contratacao = dates[0] if dates else None
        data_vencimento = dates[1] if len(dates) >= 2 else (dates[0] if len(dates) == 1 and not data_contratacao else None)

        # If only one date and we have enough values, it's likely contratação
        if len(dates) == 1:
            data_contratacao = dates[0]
            data_vencimento = None

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            if classe == "Fundo de Investimento":
                tipo_ativo = "Fundo"
            elif classe == "Renda Variável":
                tipo_ativo = "FII"
            elif classe == "Previdência":
                tipo_ativo = "Previdência"
            elif classe == "COE":
                tipo_ativo = "COE"
            else:
                tipo_ativo = "CDB"

        actual_classe = classify_classe(tipo_ativo)
        if classe:
            actual_classe = classe

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo=tipo_ativo,
            data_aplicacao=parse_date(data_contratacao) if data_contratacao else None,
            indexador="-",
            taxa=None,
            vencimento=parse_date(data_vencimento) if data_vencimento else None,
            liquidez=None,
            valor_aplicado=valor_investido,
            valor_bruto=saldo_bruto,
            valor_liquido=saldo_liquido,
            classe=actual_classe,
            subclasse=subclasse,
        ), consumed
