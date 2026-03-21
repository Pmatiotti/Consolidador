"""Parser de texto bruto para Book de Investimentos do Santander."""

import logging
import re
from typing import List, Optional, Tuple

from models.asset import Asset
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
from utils.number_parser import parse_br

logger = logging.getLogger(__name__)

BROKER = "Santander"

# Seções que encerram a área de posições — PARAR de parsear
_STOP_SECTIONS = (
    "MOVIMENTAÇÃO", "MOVIMENTACAO",
    "RENTABILIDADE DE FUNDOS",
    "NOTAS EXPLICATIVAS",
    "DISTRIBUIÇÃO DE LIQUIDEZ", "DISTRIBUICAO DE LIQUIDEZ",
)


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
        is_fundos = False

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            upper = line.upper()

            # --- Stop sections — fim da área de posições ---
            if any(upper.startswith(s) for s in _STOP_SECTIONS):
                break

            # --- Seção principal ---
            if self._match_section(upper, "RENDA FIXA PÓS"):
                current_classe = "Renda Fixa"
                current_subclasse = "Pós-fixado"
                is_fundos = False
                i += 1
                continue
            if self._match_section(upper, "RENDA FIXA PRÉ") or self._match_section(upper, "RENDA FIXA PRE"):
                current_classe = "Renda Fixa"
                current_subclasse = "Pré-fixado"
                is_fundos = False
                i += 1
                continue
            if self._match_section(upper, "INFLAÇÃO") or self._match_section(upper, "INFLACAO"):
                current_classe = "Renda Fixa"
                current_subclasse = "Inflação"
                is_fundos = False
                i += 1
                continue
            if self._match_section(upper, "RENDA VARIÁVEL") or self._match_section(upper, "RENDA VARIAVEL"):
                current_classe = "Renda Variável"
                current_subclasse = "Renda Variável"
                is_fundos = False
                i += 1
                continue

            # --- Subtipo ---
            if upper in ("CRI", "CRA", "LCI", "LCA", "LIG", "CDB", "LCD",
                         "DEBÊNTURES", "DEBENTURES", "NTN-B", "NTNB"):
                current_tipo = upper
                is_fundos = False
                i += 1
                continue
            if upper in ("FUNDOS DE INVESTIMENTO", "FUNDOS"):
                current_tipo = upper
                is_fundos = True
                i += 1
                continue
            if upper.startswith("MERCADO A VISTA"):
                current_tipo = "MERCADO A VISTA"
                is_fundos = False
                i += 1
                continue

            # --- Skip headers / totals ---
            if self._is_skip_line(upper):
                i += 1
                continue

            # --- Tentar detectar código de ativo ---
            if current_classe:
                if is_fundos and self._looks_like_fund_name(line):
                    asset, consumed = self._extract_fundo_block(lines, i, current_classe, current_subclasse)
                    if asset:
                        assets.append(asset)
                        i += consumed
                        continue
                elif current_tipo == "MERCADO A VISTA" and self._looks_like_rv_name(line):
                    asset, consumed = self._extract_rv_block(lines, i, current_classe, current_subclasse)
                    if asset:
                        assets.append(asset)
                        i += consumed
                        continue
                elif self._looks_like_asset_code(line):
                    asset, consumed = self._extract_rf_block(lines, i, current_classe, current_subclasse, current_tipo)
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
            "DATA COMPRA", "DATA VENCTO",
            "VALOR APLICADO", "IR PROVISIONADO", "IOF PROVISIONADO",
            "CARTEIRA", "POSIÇÃO",
            "PAGAMENTO", "RESGATE",
            "QTDE", "COTAÇÃO", "COTACAO",
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
        # Codes with spaces — short only (e.g. "LCI PRE"); reject long company names
        if re.match(r'^[A-Z][A-Z0-9\s]{2,}$', line) and len(line) <= 25:
            words = line.split()
            if len(words) <= 3:
                skip = ("EMISSOR", "TOTAL", "SUBTOTAL", "POSIÇÃO", "POSICAO",
                        "SALDO", "RENDA", "INFLAÇÃO", "INFLACAO", "ÍNDICE",
                        "INDICE", "TAXA", "DATA", "VALOR", "RENTAB", "CARTEIRA",
                        "IOF", "NOTAS", "MOVIMENT", "DISTRIBUI", "PAGAMENTO",
                        "RESGATE", "QTDE", "COTAÇÃO", "COTACAO")
                if not any(upper.startswith(s) for s in skip):
                    return True
        return False

    @staticmethod
    def _looks_like_fund_name(line: str) -> bool:
        """Fund names: any text with letters that's not a header/skip/number."""
        if not line or len(line) < 3:
            return False
        if not re.search(r'[A-Za-z]', line):
            return False
        if line.startswith('R$') or line == '-':
            return False
        if re.match(r'^\d{2}/\d{2}/\d{4}$', line):
            return False
        if re.match(r'^[\d.,]+$', line):
            return False
        upper = line.upper()
        skip = ("EMISSOR", "TOTAL", "SUBTOTAL", "TAXA", "ÍNDICE", "INDICE",
                "DATA", "VALOR", "SALDO", "POSIÇÃO", "POSICAO", "RENTAB",
                "CARTEIRA", "QTDE", "COTAÇÃO", "COTACAO", "PAGAMENTO",
                "RESGATE", "IOF", "NOTAS", "MOVIMENT", "DISTRIBUI", "%")
        return not any(upper.startswith(s) for s in skip)

    @staticmethod
    def _looks_like_rv_name(line: str) -> bool:
        """RV names: company name or ticker (text with letters)."""
        if not line or len(line) < 3:
            return False
        if not re.search(r'[A-Za-z]', line):
            return False
        if line.startswith('R$') or line == '-':
            return False
        if re.match(r'^\d{2}/\d{2}/\d{4}$', line):
            return False
        if re.match(r'^[\d.,]+$', line):
            return False
        upper = line.upper()
        skip = ("EMISSOR", "TOTAL", "SUBTOTAL", "TAXA", "ÍNDICE", "INDICE",
                "DATA", "VALOR", "SALDO", "POSIÇÃO", "POSICAO", "RENTAB",
                "CARTEIRA", "QTDE", "COTAÇÃO", "COTACAO", "PAGAMENTO",
                "RESGATE", "IOF", "NOTAS", "MOVIMENT", "DISTRIBUI", "%")
        return not any(upper.startswith(s) for s in skip)

    def _collect_block(self, lines: list, start_idx: int,
                       max_lines: int = 25, is_fundos: bool = False,
                       is_rv: bool = False) -> Tuple[List[str], int]:
        """Collect consecutive data lines for an asset block.

        Returns (block_lines, lines_consumed).
        """
        block: List[str] = []
        found_numbers = 0

        for j in range(start_idx, min(start_idx + max_lines, len(lines))):
            item = lines[j].strip()
            item_upper = item.upper()

            if j > start_idx:
                # Stop at section/header/subtipo boundaries
                if (self._is_section_line(item_upper)
                        or self._is_subtipo_line(item_upper)
                        or any(item_upper.startswith(s) for s in _STOP_SECTIONS)):
                    break
                # Stop at skip lines (headers, totals)
                if self._is_skip_line(item_upper):
                    break
                # After enough numbers, check for next asset
                if found_numbers >= 3:
                    if is_fundos and self._looks_like_fund_name(item):
                        break
                    elif is_rv and self._looks_like_rv_name(item):
                        break
                    elif self._looks_like_asset_code(item):
                        break

            block.append(item)

            if re.match(r'^[\d.,]+$', item) or re.match(r'^\d{2}/\d{2}/\d{4}$', item):
                found_numbers += 1

        return block, len(block)

    # ------------------------------------------------------------------
    # RF block extraction
    # ------------------------------------------------------------------
    def _extract_rf_block(self, lines: list, start_idx: int,
                          classe: str, subclasse: str, tipo: str):
        """Extract RF asset from sequential lines. Returns (Asset|None, consumed)."""
        block, consumed = self._collect_block(lines, start_idx, is_fundos=False, is_rv=False)
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
            # Percentual — skip
            if re.match(r'^-?[\d.,]+%$', item):
                continue
            # Pure number
            if re.match(r'^[\d.,]+$', item):
                numbers_found.append(item)
                continue
            # Text line — likely emissor (first text line only)
            if re.search(r'[A-Za-z]', item) and j <= 4 and not emissor:
                emissor = item
                continue

        # --- Map values ---
        # Order: taxa, valor_aplicado, saldo_bruto, ..., saldo_liquido
        if numbers_found:
            taxa_str = numbers_found[0].replace('.', '').replace(',', '.')
            try:
                taxa_val = round(float(taxa_str), 2)
            except (ValueError, TypeError):
                pass

        if len(numbers_found) >= 3:
            valor_aplicado = parse_br(numbers_found[1])
            saldo_bruto = parse_br(numbers_found[2])
        elif len(numbers_found) >= 2:
            saldo_bruto = parse_br(numbers_found[1])

        # saldo_liquido: find a large value after saldo_bruto
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

        if not saldo_bruto or saldo_bruto == 0:
            return None, consumed

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

        nome = f"{codigo} - {emissor}" if emissor else codigo

        # Determine tipo_ativo — force from current_tipo for debêntures
        tipo_ativo = classify_asset(nome)
        if tipo in ("DEBÊNTURES", "DEBENTURES"):
            tipo_ativo = "DEB"
        elif tipo_ativo == "Outro":
            tipo_map = {
                "CRI": "CRI", "CRA": "CRA", "LCI": "LCI", "LCA": "LCA",
                "LIG": "LIG", "LCD": "LCD", "CDB": "CDB",
                "NTN-B": "NTN-B", "NTNB": "NTN-B",
            }
            tipo_ativo = tipo_map.get(tipo, "CDB")

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
            classe=classe if classe else classify_classe(tipo_ativo),
            subclasse=subclasse if subclasse else "-",
        ), consumed

    # ------------------------------------------------------------------
    # RV / MERCADO A VISTA block extraction
    # ------------------------------------------------------------------
    def _extract_rv_block(self, lines: list, start_idx: int,
                          classe: str, subclasse: str):
        """Extract Renda Variável (MERCADO A VISTA) asset.

        Columns: Código | Emissor | Qtde | Qtde Bloqueada | Cotação | Saldo Bruto | ...
        The saldo_bruto is the LARGEST number in the block.
        """
        block, consumed = self._collect_block(lines, start_idx, is_rv=True)
        if consumed < 2:
            return None, 1

        codigo = block[0]
        emissor = ""
        numbers_found: List[float] = []

        for j, item in enumerate(block[1:], 1):
            # Skip percentuals, IOF, IR lines
            item_upper = item.upper()
            if any(kw in item_upper for kw in ["IOF", "IR ", "PROVISIONADO"]):
                continue
            if re.match(r'^-?[\d.,]+%$', item):
                continue
            # Pure number
            if re.match(r'^[\d.,]+$', item):
                val = parse_br(item)
                if val is not None:
                    numbers_found.append(val)
                continue
            # Text — emissor
            if re.search(r'[A-Za-z]', item) and j <= 3 and not emissor:
                emissor = item
                continue

        if not numbers_found:
            return None, consumed

        # Saldo bruto = largest number in the block
        saldo_bruto = max(numbers_found)
        if saldo_bruto == 0:
            return None, consumed

        nome = f"{codigo} - {emissor}" if emissor else codigo

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            tipo_ativo = "FII"

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo=tipo_ativo,
            data_aplicacao=None,
            indexador="Renda Variável",
            taxa=None,
            vencimento=None,
            liquidez=None,
            valor_aplicado=None,
            valor_bruto=saldo_bruto,
            valor_liquido=None,
            classe=classe if classe else "Renda Variável",
            subclasse=subclasse if subclasse else "Renda Variável",
        ), consumed

    # ------------------------------------------------------------------
    # Fundos block extraction
    # ------------------------------------------------------------------
    def _extract_fundo_block(self, lines: list, start_idx: int,
                             classe: str, subclasse: str):
        """Extract Fundo de Investimento asset.

        Fundos have NO taxa column. Numbers are: qtde cotas, valor cota, saldo bruto.
        Saldo bruto is the largest number.
        """
        block, consumed = self._collect_block(lines, start_idx, is_fundos=True)
        if consumed < 2:
            return None, 1

        nome = block[0]
        dates_found: List[str] = []
        numbers_found: List[float] = []

        for item in block[1:]:
            if re.match(r'^\d{2}/\d{2}/\d{4}$', item):
                dates_found.append(item)
                continue
            if re.match(r'^-?[\d.,]+%$', item):
                continue
            if re.match(r'^[\d.,]+$', item):
                val = parse_br(item)
                if val is not None:
                    numbers_found.append(val)
                continue

        if not numbers_found:
            return None, consumed

        # Saldo bruto = LAST number (after cotas, cota_value)
        saldo_bruto = numbers_found[-1]
        if saldo_bruto == 0:
            return None, consumed

        data_aplicacao = dates_found[0] if dates_found else None

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            tipo_ativo = "Fundo"

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo=tipo_ativo,
            data_aplicacao=parse_date(data_aplicacao),
            indexador="-",
            taxa=None,
            vencimento=None,
            liquidez=None,
            valor_aplicado=None,
            valor_bruto=saldo_bruto,
            valor_liquido=None,
            classe="Fundo de Investimento",
            subclasse=subclasse if subclasse else "-",
        ), consumed
