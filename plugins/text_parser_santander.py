"""Parser de texto bruto para Book de Investimentos do Santander."""

import logging
import re
from typing import List, Optional

from models.asset import Asset
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
from utils.number_parser import parse_br

logger = logging.getLogger(__name__)

BROKER = "Santander"


class SantanderTextParser:
    """Parser de texto para Book de Investimentos do Santander.

    Nenhum plugin detecta este PDF e os engines de tabela falham nas
    páginas de detalhe.  Trabalha com texto bruto (page.get_text()).
    """

    BROKER = BROKER

    @staticmethod
    def can_handle(text: str) -> bool:
        lower = text.lower()
        return "santander" in lower and \
               ("book de investimentos" in lower or "posição detalhada" in lower)

    def extract_from_text(self, full_text: str) -> List[Asset]:
        assets: List[Asset] = []
        lines = full_text.split('\n')

        current_classe = ""
        current_subclasse = ""
        current_tipo = ""

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            upper = line.upper()

            # --- Seção principal ---
            if self._match_section(upper, "RENDA FIXA PÓS"):
                current_classe = "Renda Fixa"
                current_subclasse = "Pós-fixado"
                i += 1
                continue
            if self._match_section(upper, "RENDA FIXA PRÉ") or self._match_section(upper, "RENDA FIXA PRE"):
                current_classe = "Renda Fixa"
                current_subclasse = "Pré-fixado"
                i += 1
                continue
            if self._match_section(upper, "INFLAÇÃO") or self._match_section(upper, "INFLACAO"):
                current_classe = "Renda Fixa"
                current_subclasse = "Inflação"
                i += 1
                continue
            if self._match_section(upper, "RENDA VARIÁVEL") or self._match_section(upper, "RENDA VARIAVEL"):
                current_classe = "Renda Variável"
                current_subclasse = "Renda Variável"
                i += 1
                continue

            # --- Subtipo ---
            if upper in ("CRI", "CRA", "LCI", "LIG", "LCA", "CDB", "LCD",
                         "DEBÊNTURES", "DEBENTURES", "NTN-B", "NTNB",
                         "FUNDOS DE INVESTIMENTO", "FUNDOS"):
                current_tipo = upper
                i += 1
                continue
            if upper.startswith("MERCADO A VISTA"):
                current_tipo = "MERCADO A VISTA"
                i += 1
                continue

            # --- Skip headers / totals ---
            if self._is_skip_line(upper):
                i += 1
                continue

            # --- Tentar detectar código de ativo ---
            if self._looks_like_asset_code(line) and current_classe:
                asset, consumed = self._extract_asset_block(
                    lines, i, current_classe, current_subclasse, current_tipo
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
    def _match_section(upper_line: str, section: str) -> bool:
        return upper_line == section or upper_line.startswith(section + " ") or \
               upper_line.startswith(section + "\t")

    @staticmethod
    def _is_subtipo_line(upper: str) -> bool:
        subtipos = ("CRI", "CRA", "LCI", "LCA", "LIG", "CDB", "LCD",
                     "DEBÊNTURES", "DEBENTURES", "NTN-B", "NTNB",
                     "FUNDOS DE INVESTIMENTO", "FUNDOS", "MERCADO A VISTA")
        return upper in subtipos or any(upper.startswith(s + " ") for s in subtipos)

    @staticmethod
    def _is_section_line(upper: str) -> bool:
        sections = ("RENDA FIXA PÓS", "RENDA FIXA PRÉ", "RENDA FIXA PRE",
                     "INFLAÇÃO", "INFLACAO", "RENDA VARIÁVEL", "RENDA VARIAVEL")
        return any(upper == s or upper.startswith(s + " ") or upper.startswith(s + "\t")
                   for s in sections)

    @staticmethod
    def _is_skip_line(upper: str) -> bool:
        skip_keywords = (
            "EMISSOR", "TAXA ANO", "TAXA", "ÍNDICE", "INDICE",
            "POSIÇÃO DETALHADA", "POSIÇÃO CONSOLIDADA", "POSICAO",
            "SUBTOTAL", "TOTAL", "SALDO BRUTO", "SALDO LÍQUIDO",
            "RENTAB", "% DA CARTEIRA", "% DA",
            "MOVIMENTAÇÃO", "RENTABILIDADE DE FUNDOS", "NOTAS EXPLICATIVAS",
            "DISTRIBUIÇÃO DE LIQUIDEZ", "DATA COMPRA", "DATA VENCTO",
            "VALOR APLICADO", "IR PROVISIONADO", "IOF PROVISIONADO",
            "CARTEIRA", "POSIÇÃO",
        )
        return any(upper.startswith(kw) or upper == kw for kw in skip_keywords)

    @staticmethod
    def _looks_like_asset_code(line: str) -> bool:
        if not line or len(line) < 3:
            return False
        if line.startswith('R$') or '%' in line:
            return False
        if re.match(r'^\d{2}/\d{2}/\d{4}$', line):
            return False
        if re.match(r'^[\d.,]+$', line):
            return False
        # Exclude known index patterns
        upper = line.upper().strip()
        if upper in ("DI 100", "PRE 100", "IPCA 100", "DI100", "PRE100", "IPCA100"):
            return False
        # Pure alphanumeric code (e.g. "23H1037957", "CRA02300S37", "VRTA11")
        if re.match(r'^[A-Z0-9]{3,25}$', line):
            return True
        # Codes with spaces — short only (e.g. "LCI PRE"); long multi-word
        # strings are likely emissor names, not codes
        if re.match(r'^[A-Z][A-Z0-9\s]{2,}$', line) and len(line) <= 25:
            # Reject if it has 3+ words (likely a company name)
            words = line.split()
            if len(words) <= 3:
                skip = ("EMISSOR", "TOTAL", "SUBTOTAL", "POSIÇÃO", "POSICAO",
                        "SALDO", "RENDA", "INFLAÇÃO", "INFLACAO", "ÍNDICE",
                        "INDICE", "TAXA", "DATA", "VALOR", "RENTAB", "CARTEIRA",
                        "IOF", "NOTAS", "MOVIMENT", "DISTRIBUI")
                if not any(upper.startswith(s) for s in skip):
                    return True
        return False

    def _extract_asset_block(self, lines: list, start_idx: int,
                             classe: str, subclasse: str, tipo: str):
        """Extrai dados de um bloco sequencial de linhas que formam um ativo.

        Returns (Asset | None, lines_consumed).
        """
        block: List[str] = []
        # Collect lines until we hit a section boundary or another asset code.
        # Lines 1-3 after the code are emissor/taxa/index — never terminate there
        # to avoid confusing all-caps emissor names with asset codes.
        found_numbers = 0
        for j in range(start_idx, min(start_idx + 25, len(lines))):
            item = lines[j].strip()
            item_upper = item.upper()

            if j > start_idx:
                # Always stop at section/header/subtipo boundaries
                if (self._is_section_line(item_upper)
                        or self._is_skip_line(item_upper)
                        or self._is_subtipo_line(item_upper)):
                    break

                # Only check for asset code after we've seen numeric data
                # (emissor lines come before numbers)
                if found_numbers >= 3 and self._looks_like_asset_code(item):
                    break

            block.append(item)

            # Track numeric lines to know when data block has started
            if re.match(r'^[\d.,]+$', item) or re.match(r'^\d{2}/\d{2}/\d{4}$', item):
                found_numbers += 1

        consumed = len(block)
        if consumed < 2:
            return None, 1

        codigo = block[0]
        emissor = ""
        taxa_val = None
        indice = ""
        data_compra = None
        data_vencto = None
        valor_aplicado = None
        saldo_bruto = None
        saldo_liquido = None

        numbers_found: List[str] = []
        dates_found: List[str] = []

        for j, item in enumerate(block[1:], 1):
            # Date
            if re.match(r'^\d{2}/\d{2}/\d{4}$', item):
                dates_found.append(item)
                continue
            # Índice patterns
            if item.upper() in ("DI 100", "PRE 100", "IPCA 100",
                                "DI100", "PRE100", "IPCA100"):
                indice = item.upper().replace("100", " 100").replace("  ", " ")
                continue
            # Percentual (rentabilidade mês, % carteira — skip)
            if re.match(r'^-?[\d.,]+%$', item):
                continue
            # Pure number
            if re.match(r'^[\d.,]+$', item):
                numbers_found.append(item)
                continue
            # Text line — likely emissor (only first few text lines)
            if re.search(r'[A-Za-z]', item) and j <= 4 and not emissor:
                emissor = item
                continue

        # --- Map extracted data ---
        is_rv = (classe == "Renda Variável")

        if is_rv:
            # RV: no taxa, no index, no dates — numbers are saldo_bruto, valor_aplicado
            if numbers_found:
                saldo_bruto = parse_br(numbers_found[0])
            if len(numbers_found) >= 2:
                valor_aplicado = parse_br(numbers_found[1])
            indexador = "Renda Variável"
        else:
            # RF: first number = taxa (e.g. "1,30000", "12,45000")
            if numbers_found:
                taxa_str = numbers_found[0].replace('.', '').replace(',', '.')
                try:
                    taxa_val = round(float(taxa_str), 2)
                except (ValueError, TypeError):
                    pass

            # valor_aplicado & saldo_bruto
            if len(numbers_found) >= 3:
                valor_aplicado = parse_br(numbers_found[1])
                saldo_bruto = parse_br(numbers_found[2])
            elif len(numbers_found) >= 2:
                saldo_bruto = parse_br(numbers_found[1])

            # saldo_liquido: look for a large value after saldo_bruto
            # Skip rentab(%), IR, IOF (small values) and find saldo_liquido
            if len(numbers_found) >= 4:
                for n in numbers_found[3:]:
                    val = parse_br(n)
                    if val and val > 100:
                        saldo_liquido = val
                        break

            if dates_found:
                data_compra = dates_found[0]
            if len(dates_found) >= 2:
                data_vencto = dates_found[1]

            # Determine indexador
            indice_clean = indice.replace(" ", "").upper()
            if indice_clean == "DI100":
                indexador = "CDI +"
            elif indice_clean == "PRE100":
                indexador = "Prefixado"
            elif indice_clean == "IPCA100":
                indexador = "IPCA +"
            else:
                indexador = "-"

            # Taxa 0.00 with IPCA is valid
            if indexador == "IPCA +" and taxa_val == 0.0:
                taxa_val = 0.0

        if not saldo_bruto or saldo_bruto == 0:
            return None, consumed

        nome = f"{codigo} - {emissor}" if emissor else codigo

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            tipo_map = {
                "CRI": "CRI", "CRA": "CRA", "LCI": "LCI", "LCA": "LCA",
                "LIG": "LIG", "LCD": "LCD", "CDB": "CDB",
                "DEBÊNTURES": "DEB", "DEBENTURES": "DEB",
                "NTN-B": "NTN-B", "NTNB": "NTN-B",
                "MERCADO A VISTA": "FII",
                "FUNDOS DE INVESTIMENTO": "Fundo", "FUNDOS": "Fundo",
            }
            tipo_ativo = tipo_map.get(tipo, "CDB")

        final_classe = classe if classe else classify_classe(tipo_ativo)
        final_subclasse = subclasse if subclasse else "-"

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo=tipo_ativo,
            data_aplicacao=parse_date(data_compra),
            indexador=indexador,
            taxa=taxa_val,
            vencimento=parse_date(data_vencto),
            liquidez=None,
            valor_aplicado=valor_aplicado,
            valor_bruto=saldo_bruto,
            valor_liquido=saldo_liquido,
            classe=final_classe,
            subclasse=final_subclasse,
        ), consumed
