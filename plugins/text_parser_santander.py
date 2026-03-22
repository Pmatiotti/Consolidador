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
        if "santander" not in lower:
            return False
        return ("book de investimentos" in lower or "posição detalhada" in lower
                or ("book " in lower and "crédito privado" in lower))

    def extract_from_text(self, full_text: str) -> List[Asset]:
        assets: List[Asset] = []

        # Try Book format (CRÉDITO PRIVADO sections)
        if self._is_book_format(full_text):
            book_assets = self._parse_book_format(full_text)
            if book_assets:
                return self._cleanup(book_assets)

        # Try standard Posição Detalhada format
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
                if upper != current_tipo:
                    current_tipo = upper
                    is_fundos = False
                    i += 1
                    continue
                # else: same subtipo — fall through to asset detection
            if upper in ("FUNDOS DE INVESTIMENTO", "FUNDOS"):
                current_tipo = upper
                is_fundos = True
                i += 1
                continue
            if upper.startswith("MERCADO A VISTA"):
                current_tipo = "MERCADO A VISTA"
                current_subclasse = "Ações"
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

        # Final cleanup: filter skip names and deduplicate
        assets = self._cleanup(assets)
        return assets

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup(assets: list) -> list:
        """Remove skip-name assets and deduplicate by bruto value."""
        skip_names = ("total", "subtotal", "fundos de investimento",
                      "posição consolidada", "posicao consolidada",
                      "posição detalhada", "posicao detalhada",
                      "movimentação", "movimentacao", "rentabilidade")

        # Step 1: filter skip names
        filtered = [a for a in assets
                    if not any(s in a.ativo.lower() for s in skip_names)]

        # Step 2: deduplicate — if two assets have the same bruto value,
        # keep the one with the longer (more descriptive) name
        seen_bruto: dict = {}  # bruto_rounded -> index in unique list
        unique = []
        for a in filtered:
            key = round(a.valor_bruto, 2) if a.valor_bruto else 0
            if key > 0 and key in seen_bruto:
                # Keep the more descriptive one (longer name)
                existing_idx = seen_bruto[key]
                if len(a.ativo) > len(unique[existing_idx].ativo):
                    unique[existing_idx] = a
                # else: keep existing (already more descriptive)
            else:
                seen_bruto[key] = len(unique)
                unique.append(a)

        return unique

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
        # "TESOURO ..." pattern (e.g. "TESOURO IPCA 2035")
        if upper.startswith("TESOURO"):
            return True
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
        # For TESOURO/NTN-B: no taxa column, numbers are cotas/cota_val/bruto/liquido
        is_tesouro = "TESOURO" in codigo.upper() or "NTN" in codigo.upper()

        if is_tesouro:
            # Skip first 2 numbers (cotas + cota value), rest are monetary
            all_big: List[float] = []
            skip_count = 2
            for idx_n, n in enumerate(numbers_found):
                val = parse_br(n)
                if idx_n < skip_count:
                    continue
                if val and val > 100:
                    all_big.append(val)
            if len(all_big) >= 1:
                saldo_bruto = all_big[0]
            if len(all_big) >= 2:
                saldo_liquido = all_big[1]
            # TESOURO/NTN-B in Inflação section: indexador = IPCA +
            if not indice:
                indice = "IPCA 100"
        else:
            # Standard RF: first number is taxa (small); remaining big numbers are monetary
            if numbers_found:
                taxa_str = numbers_found[0].replace('.', '').replace(',', '.')
                try:
                    taxa_val = round(float(taxa_str), 2)
                except (ValueError, TypeError):
                    pass

            # Filter monetary values (>100) from remaining numbers
            big_numbers: List[float] = []
            for n in numbers_found[1:]:
                val = parse_br(n)
                if val and val > 100:
                    big_numbers.append(val)

            if len(big_numbers) >= 1:
                valor_aplicado = big_numbers[0]
            if len(big_numbers) >= 2:
                saldo_bruto = big_numbers[1]
            if len(big_numbers) >= 3:
                saldo_liquido = big_numbers[2]

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

        # Fundos sequence: qtde_cotas, valor_cota, saldo_bruto, [IR, IOF], saldo_liquido
        # Skip first 2 numbers (cotas + cota value), then filter big values
        remaining = numbers_found[2:] if len(numbers_found) > 2 else numbers_found
        big_numbers = [n for n in remaining if n > 100]
        if not big_numbers:
            return None, consumed

        saldo_bruto = big_numbers[0]
        saldo_liquido = big_numbers[1] if len(big_numbers) >= 2 else None

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
            valor_liquido=saldo_liquido,
            classe="Fundo de Investimento",
            subclasse=subclasse if subclasse else "-",
        ), consumed

    # ------------------------------------------------------------------
    # Book Santander format (CRÉDITO PRIVADO sections)
    # ------------------------------------------------------------------
    @staticmethod
    def _is_book_format(text: str) -> bool:
        """Detect Book Santander format (BOOK FEVEREIRO, etc.)."""
        lower = text.lower()
        return "crédito privado" in lower or "credito privado" in lower

    def _parse_book_format(self, full_text: str) -> List[Asset]:
        """Parse Book Santander 'Posição Detalhada de Produtos' page.

        Structure per asset type:
        - DEBENTURES: [section] date R$-bruto R$-disp R$-invested tax ...headers... venc qtde EMISSOR
        - FUNDOS: [section] [headers] NAME date R$-bruto R$-disp R$-cota qtde_cotas ...
        - CDB: [section] [headers] NAME date R$-bruto R$-disp prazo tax [venc-header] venc
        - POUPANÇA: [section] [headers] NAME date R$-bruto R$-disp
        """
        # Normalize non-breaking spaces (U+00A0) that appear in R$ values
        text = full_text.replace('\xa0', ' ')
        lines = [ln.strip() for ln in text.split('\n')]

        # Anchor to the "Posição Detalhada de Produtos" page (ASCII substring match)
        start_line = 0
        for idx, ln in enumerate(lines):
            if 'detalhada de produtos' in ln.lower():
                start_line = idx
                break

        assets = []
        current_type = None   # 'DEBENTURES', 'FUNDOS', 'CDB', 'POUPANCA'

        # Known header fragments to skip
        _HDR = ('produto', 'data de', 'contrata', 'saldo bruto', 'valor disp',
                'resgate', 'valor investido', 'rentabilidade', 'contratada',
                'valor da cota', 'quantidade de cotas', 'quantidade de',
                'quantidade', 'de cotas', 'de sa', '(r',
                'data da cota', 'valor da taxa', 'prazo',
                'data de vencimento', 'vencimento',
                'emissor', 'ativos', 'gerado em',
                'book de', 'privado')

        def _skip(ln: str) -> bool:
            lo = ln.lower()
            if not ln or re.match(r'^\d{1,2}$', ln):
                return True
            return any(lo.startswith(h) for h in _HDR)

        def _is_date(ln: str) -> bool:
            return bool(re.match(r'^\d{2}/\d{2}/\d{4}$', ln))

        def _get_r(ln: str):
            """Return numeric value if line is an R$ value line, else None."""
            m = re.search(r'R\$\s*([\d.,]+)', ln)
            return parse_br(m.group(1)) if m else None

        def _is_sub_type(ln: str) -> str:
            """Return normalised sub-type name or ''."""
            u = ln.upper().strip()
            if u == 'DEBENTURES':
                return 'DEBENTURES'
            if u == 'FUNDOS':
                return 'FUNDOS'
            if u == 'CDB':
                return 'CDB'
            if u in ('POUPANÇA', 'POUPANCA'):
                return 'POUPANCA'
            return ''

        i = start_line
        while i < len(lines):
            line = lines[i]
            upper = line.upper()

            # Stop when we reach a new page that is NOT "Detalhada de Produtos"
            if ('book de investimentos' in line.lower()
                    and 'detalhada' not in line.lower()
                    and i > start_line + 5):
                break

            # Detect sub-type section headers
            st = _is_sub_type(line)
            if st:
                current_type = st
                i += 1
                continue

            if current_type is None or _skip(line):
                i += 1
                continue

            # ---- DEBENTURES: entry starts with a date (data contratação) ----
            if current_type == 'DEBENTURES' and _is_date(line):
                data_aplic = line
                r_values = []
                taxa_raw = ''
                emissor = ''
                j = i + 1
                while j < min(i + 20, len(lines)):
                    ln = lines[j]
                    rv = _get_r(ln)
                    if rv is not None:
                        r_values.append(rv)
                    elif _is_date(ln) and emissor:
                        pass  # data vencimento — ignore for now
                    elif re.match(r'^\d{1,3}$', ln):
                        pass  # quantidade de ativos
                    elif ('CDI' in ln.upper() or 'IPCA' in ln.upper()
                          or 'IGPM' in ln.upper() or ('%' in ln and re.search(r'\d', ln))):
                        taxa_raw = ln
                    elif re.search(r'[A-Za-z]', ln) and not _skip(ln) and len(ln) > 2:
                        # First meaningful text after values = emissor name
                        if r_values:
                            emissor = ln
                            j += 1
                            break
                    j += 1
                consumed = j - i

                saldo_bruto = r_values[0] if r_values else None
                saldo_liquido = r_values[1] if len(r_values) >= 2 else saldo_bruto

                if saldo_bruto and emissor:
                    # Determine indexador from taxa_raw
                    if 'IPCA' in taxa_raw.upper():
                        indexador = 'IPCA +'
                    elif 'CDI' in taxa_raw.upper():
                        indexador = '% CDI'
                    else:
                        indexador = '-'

                    assets.append(Asset(
                        corretora=BROKER,
                        ativo=f'DEB {emissor}',
                        tipo_ativo='DEB',
                        data_aplicacao=parse_date(data_aplic),
                        indexador=indexador,
                        taxa=None,
                        vencimento=None,
                        liquidez=None,
                        valor_aplicado=None,
                        valor_bruto=saldo_bruto,
                        valor_liquido=saldo_liquido,
                        classe='Renda Fixa',
                        subclasse='Inflação' if 'IPCA' in taxa_raw.upper() else 'Pós-fixado',
                    ))
                i += consumed
                continue

            # ---- FUNDOS / CDB / POUPANCA: entry starts with product name ----
            if current_type in ('FUNDOS', 'CDB', 'POUPANCA'):
                # Must not start with R$ (avoid picking up zero-value R$ lines)
                if (not _is_date(line) and _get_r(line) is None
                        and not line.startswith('R$')
                        and re.search(r'[A-Za-z]', line)):
                    # This is the product name (possibly multi-line)
                    nome_parts = [line]
                    j = i + 1
                    # Check if next line is a continuation (short, no date/R$)
                    if j < len(lines):
                        nxt = lines[j]
                        if (nxt and not _is_date(nxt) and _get_r(nxt) is None
                                and not nxt.startswith('R$')
                                and not _skip(nxt) and re.search(r'[A-Za-z]', nxt)
                                and len(nxt) <= 10):
                            nome_parts.append(nxt)
                            j += 1
                    nome = ' '.join(nome_parts)

                    r_values = []
                    data_aplic = None
                    taxa_raw = ''
                    while j < min(i + 15, len(lines)):
                        ln = lines[j]
                        # Hard stop: new page boundary
                        if 'book de investimentos' in ln.lower():
                            break
                        rv = _get_r(ln)
                        if rv is not None:
                            r_values.append(rv)
                        elif _is_date(ln) and not data_aplic:
                            data_aplic = ln
                        elif ('CDI' in ln.upper() or 'IPCA' in ln.upper()
                              or ('%' in ln and re.search(r'\d', ln))):
                            taxa_raw = ln
                        elif re.match(r'^\d{1,3}$', ln):
                            pass  # qtde ativos
                        elif _skip(ln):
                            pass
                        elif (re.search(r'[A-Za-z]', ln) and r_values
                              and not re.match(r'^\d', ln)
                              and not ln.startswith('R$')):
                            # Next product name — stop
                            break
                        j += 1

                    consumed = j - i
                    saldo_bruto = r_values[0] if r_values else None
                    saldo_liquido = r_values[1] if len(r_values) >= 2 else saldo_bruto

                    if saldo_bruto and saldo_bruto > 0 and nome:
                        tipo_ativo = classify_asset(nome)
                        if tipo_ativo == 'Outro':
                            if current_type == 'FUNDOS':
                                tipo_ativo = 'Fundo'
                            elif current_type == 'CDB':
                                tipo_ativo = 'CDB'
                            else:
                                tipo_ativo = 'Poupança'

                        classe = classify_classe(tipo_ativo)
                        if 'CDI' in taxa_raw.upper() or current_type == 'CDB':
                            subclasse = 'Pós-fixado'
                        elif current_type == 'FUNDOS':
                            subclasse = 'Multimercado'
                        elif current_type == 'POUPANCA':
                            subclasse = 'Poupança'
                        else:
                            subclasse = '-'

                        indexador = '% CDI' if subclasse == 'Pós-fixado' else '-'

                        assets.append(Asset(
                            corretora=BROKER,
                            ativo=nome,
                            tipo_ativo=tipo_ativo,
                            data_aplicacao=parse_date(data_aplic) if data_aplic else None,
                            indexador=indexador,
                            taxa=None,
                            vencimento=None,
                            liquidez=None,
                            valor_aplicado=None,
                            valor_bruto=saldo_bruto,
                            valor_liquido=saldo_liquido,
                            classe=classe,
                            subclasse=subclasse,
                        ))
                    i += consumed
                    continue

            i += 1

        return assets

    @staticmethod
    def _looks_like_book_product(line: str) -> bool:
        """Book product names: text with letters, not headers."""
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
        # Reject parenthesized currency markers like "(R$)"
        if re.match(r'^\(R\$\)', line.strip()):
            return False
        # Reject lines that are only punctuation/symbols with R$
        if re.match(r'^[\(\)R\$\s]+$', line.strip()):
            return False
        upper = line.upper()
        skip = ("EMISSOR", "TOTAL", "SUBTOTAL", "TAXA", "ÍNDICE", "INDICE",
                "DATA", "VALOR", "SALDO", "POSIÇÃO", "POSICAO", "RENTAB",
                "CARTEIRA", "PRODUTO", "CONTRATAÇÃO", "CONTRATACAO",
                "RESGATE", "PAGAMENTO", "NOTAS", "MOVIMENT", "DISTRIBUI",
                "%", "CRÉDITO", "CREDITO", "QUANTIDADE", "QTDE",
                "VENCIMENTO", "LIQUIDEZ", "DISPONÍVEL", "DISPONIVEL")
        return not any(upper.startswith(s) for s in skip)

    def _extract_book_product(self, lines: list, start_idx: int,
                               subclasse: str):
        """Extract a product from Book format.

        Product name on first line, followed by date and numeric values.
        """
        nome = lines[start_idx].strip()
        dates_found = []
        numbers_found = []
        consumed = 1

        for j in range(start_idx + 1, min(start_idx + 15, len(lines))):
            item = lines[j].strip()
            item_upper = item.upper()

            # Stop at section boundaries
            if (self._is_section_line(item_upper)
                    or any(item_upper.startswith(s) for s in _STOP_SECTIONS)):
                break
            if self._is_skip_line(item_upper):
                break

            # Stop at next product (after collecting some data)
            if numbers_found and self._looks_like_book_product(item):
                break

            consumed += 1

            # Date
            if re.match(r'^\d{2}/\d{2}/\d{4}$', item):
                dates_found.append(item)
                continue

            # Percentage — skip
            if re.match(r'^-?[\d.,]+%$', item):
                continue

            # Pure number
            if re.match(r'^[\d.,]+$', item):
                val = parse_br(item)
                if val is not None:
                    numbers_found.append(val)
                continue

        if not numbers_found:
            return None, consumed

        # Book format: numbers are saldo_bruto, valor_disp_resgate, etc.
        # Take big numbers (>100) as monetary values
        big = [n for n in numbers_found if n > 100]
        if not big:
            return None, consumed

        saldo_bruto = big[0]
        saldo_liquido = big[1] if len(big) >= 2 else None

        data_contratacao = dates_found[0] if dates_found else None

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            upper = nome.upper()
            if any(k in upper for k in ["CDB", "LCI", "LCA", "LIG", "LCD"]):
                for k in ["CDB", "LCI", "LCA", "LIG", "LCD"]:
                    if k in upper:
                        tipo_ativo = k
                        break
            elif any(k in upper for k in ["CRI", "CRA", "DEB"]):
                for k in ["CRI", "CRA", "DEB"]:
                    if k in upper:
                        tipo_ativo = k
                        break
            else:
                tipo_ativo = "CDB"

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo=tipo_ativo,
            data_aplicacao=parse_date(data_contratacao),
            indexador="% CDI" if subclasse == "Pós-fixado" else ("IPCA +" if subclasse == "Inflação" else "Prefixado"),
            taxa=None,
            vencimento=None,
            liquidez=None,
            valor_aplicado=None,
            valor_bruto=saldo_bruto,
            valor_liquido=saldo_liquido,
            classe=classify_classe(tipo_ativo),
            subclasse=subclasse,
        ), consumed
