"""Plugin para Bradesco Principal."""

import logging
import re
from typing import List, Optional

from models.asset import Asset
from plugins.base import BrokerPlugin
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
from utils.number_parser import parse_br
from utils.tax_parser import parse_tax_bradesco

logger = logging.getLogger(__name__)

BROKER = "Bradesco"

# Mapeamento subclasse Bradesco → padrão
SUBCLASSE_MAP = {
    "cdi/selic": "Pós-fixado",
    "cdi": "Pós-fixado",
    "selic": "Pós-fixado",
    "juro real": "Inflação",
    "prefixado": "Pré-fixado",
    "pré-fixado": "Pré-fixado",
    "rv global": "RV Global",
    "rv global - moeda local": "RV Global",
    "renda variável": "Renda Variável",
}

# Header words to detect concatenated header+data cells
_HEADER_WORDS = ("produto", "ativo", "fundo", "emissor", "saldo bruto",
                 "saldo líquido", "taxa de compra", "taxa ao ano",
                 "data de aplicação", "data de venc", "valor principal",
                 "carência", "venc. da carência")


class BradescoPlugin(BrokerPlugin):
    @staticmethod
    def detect(text: str) -> bool:
        lower = text.lower()
        if "bradesco" not in lower:
            return False
        return "relatório de investimentos" in lower or "principal" in lower

    @staticmethod
    def broker_name() -> str:
        return BROKER

    def extract(self, pdf_path: str) -> List[Asset]:
        assets = []
        try:
            from utils.pdf_reader import extract_from_pdf
            full_text, all_tables = extract_from_pdf(pdf_path)
            assets = self._parse_all(all_tables, full_text)
        except Exception as e:
            logger.warning(f"Erro ao processar Bradesco PDF {pdf_path}: {e}")

        return assets

    def _parse_all(self, tables: list, full_text: str = "") -> List[Asset]:
        """Parse Bradesco tables.

        Bradesco PDFs have two table structures:
        - Type A: col-0 is a concat "Produto\\n1 Name1\\n2 Name2...", data in rows 1+
          where each data row has col-1 = product name (or None for name-from-concat)
        - Type B: no Produto column; header starts with "Data de\\naplicação";
          product name comes from the PDF text preceding the table
        """
        assets = []
        current_subclasse = "-"
        current_classe = "Renda Fixa"

        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            first_header_cell = header[0] if header else ""

            # Detect class headers from single-cell tables
            if len(header) <= 2 and first_header_cell.lower() in (
                    "renda fixa", "renda variável", "renda variavel",
                    "renda variável\n", "renda variavel\n"):
                if "variável" in first_header_cell.lower() or "variavel" in first_header_cell.lower():
                    current_classe = "Renda Variável"
                else:
                    current_classe = "Renda Fixa"
                continue

            # Detect subclasse header tables (e.g. ["CDI/Selic", R$..., %])
            # Only for simple single-line headers — concat cells may contain "cdi" in product names
            if "\n" not in first_header_cell:
                matched_sub_hdr = self._match_subclasse(first_header_cell.lower().strip())
                if matched_sub_hdr is not None:
                    current_subclasse = matched_sub_hdr
                    continue

            # ---- Type A: Produto concat cell in col 0 of row 0 ----
            if "\n" in first_header_cell and self._is_header_concat(first_header_cell):
                embedded_names = self._extract_names_from_concat(first_header_cell)
                emb_idx = 0

                for row_idx, row in enumerate(table[1:], 1):  # Skip header row
                    if not row:
                        continue
                    row_clean = [str(c).strip() if c else "" for c in row]

                    # Get nome from col 1 if it looks like a product name
                    nome = ""
                    if len(row_clean) > 1 and row_clean[1]:
                        col1 = row_clean[1].replace('\n', ' ').strip()
                        if (col1 and len(col1) >= 2
                                and not re.match(r'^\d{2}/\d{2}/\d{2,4}$', col1)
                                and not re.match(r'^[\d.,]+$', col1)
                                and not col1.startswith('R$')):
                            nome = col1
                            emb_idx += 1
                    # If no name from col 1, use next embedded name
                    if not nome and emb_idx < len(embedded_names):
                        nome = embedded_names[emb_idx]
                        emb_idx += 1

                    if not nome:
                        continue

                    # Build a virtual row with nome in position 0
                    virtual = [nome] + row_clean[1:]
                    asset = self._parse_row(virtual, header, current_classe, current_subclasse)
                    if asset:
                        assets.append(asset)
                continue

            # ---- Type B: No Produto column; header starts with "Data de\\naplicação" ----
            header_joined = " ".join(h.lower() for h in header[:3])
            if "data de" in header_joined and "produto" not in header_joined:
                # Single data row — find name from full_text context
                for row in table[1:]:
                    if not row:
                        continue
                    row_clean = [str(c).strip() if c else "" for c in row]
                    # Col 0 is the date; values at known positions
                    # Find saldo_bruto from col_map
                    col_map = {}
                    for i, h in enumerate(header):
                        col_map[h.lower().strip()] = i
                    saldo_bruto_str = ""
                    for kw in ["saldo bruto"]:
                        for hk, idx in col_map.items():
                            if kw in hk and idx < len(row_clean):
                                saldo_bruto_str = row_clean[idx]
                                break
                    vb = parse_br(saldo_bruto_str)
                    if not vb or vb == 0:
                        continue
                    # Find product name from full_text: line preceding R$vb
                    vb_str_br = f"{vb:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    nome = self._find_name_for_value(full_text, vb_str_br) or f"Bradesco Produto {vb:.0f}"

                    saldo_liquido_str = ""
                    for kw in ["saldo líquido", "saldo liquido"]:
                        for hk, idx in col_map.items():
                            if kw in hk and idx < len(row_clean):
                                saldo_liquido_str = row_clean[idx]
                                break
                    virtual = [nome] + row_clean[1:]
                    asset = self._parse_row(virtual, header, current_classe, current_subclasse)
                    if asset:
                        assets.append(asset)
                continue

        return assets

    def _is_header_concat(self, cell: str) -> bool:
        """Check if this cell is a header+data concatenation."""
        first_line = cell.split("\n")[0].strip().lower()
        return any(first_line.startswith(hw) for hw in _HEADER_WORDS)

    @staticmethod
    def _extract_names_from_concat(cell: str) -> List[str]:
        """Extract ordered product names from a concat header cell.

        Cell format: "Produto\\nPrefix\\n1 rest\\nPrefix2\\n2 rest2\\n3 Name3..."
        Non-numbered lines before a numbered line become prefixes of that product.
        Returns ["Prefix rest", "Prefix2 rest2", "Name3", ...] in order.
        """
        lines = [ln.strip() for ln in cell.split("\n") if ln.strip()]
        products = []
        pending: List[str] = []  # Non-numbered lines (prefix for next numbered item)
        for ln in lines:
            if ln.lower().startswith('produto'):
                continue
            m = re.match(r'^(\d+)\s+(.+)', ln)
            if m:
                rest = m.group(2).strip()
                full_name = " ".join(pending + [rest]).strip()
                products.append(full_name)
                pending = []
            else:
                pending.append(ln)
        return products

    @staticmethod
    def _find_name_for_value(full_text: str, value_str: str) -> str:
        """Find product name in full_text that immediately precedes an R$ value line."""
        text = full_text.replace('\xa0', ' ')
        lines = [l.strip() for l in text.split('\n')]
        skip_starts = ("total", "renda", "cdi", "selic", "juro", "prefixado",
                       "inflação", "inflacao", "composição", "composicao",
                       "produtos", "classe", "relat", "período", "periodo",
                       "valor bruto", "per", "r$")
        best_name = ""
        # Scan all occurrences and prefer one that has a real product name before it
        for i, line in enumerate(lines):
            if value_str not in line or 'R$' not in line:
                continue
            for j in range(i - 1, max(i - 6, -1), -1):
                candidate = lines[j].strip()
                if not candidate:
                    continue
                clo = candidate.lower()
                if any(clo.startswith(s) for s in skip_starts):
                    continue
                if re.match(r'^[\d.,\-\s%]+$', candidate):
                    continue
                if re.match(r'^\d{2}/\d{2}/\d{4}$', candidate):
                    continue
                if re.search(r'[A-Za-z]', candidate) and len(candidate) >= 3:
                    best_name = candidate
                    break
            if best_name:
                break
        return best_name

    def _extract_from_concat_cell(self, first_cell: str, row_clean: list,
                                   header: list, classe: str,
                                   subclasse: str) -> List[Asset]:
        """Extract products from a concatenated header+data cell.

        The cell looks like:
        "Produto\n1 Bradesco Debêntures\nIncentivadas CDI\n2 Bradesco..."

        Products are prefixed with a sequential number (1, 2, 3...).
        Multi-line product names continue until the next numbered entry.
        """
        assets = []
        lines = first_cell.split("\n")

        # Skip the header line(s)
        product_lines = []
        started = False
        for ln in lines:
            stripped = ln.strip()
            if not started:
                # Skip until we find a numbered product line
                if re.match(r'^\d+\s+', stripped):
                    started = True
                    product_lines.append(stripped)
                continue
            product_lines.append(stripped)

        if not product_lines:
            return assets

        # Group lines by numbered products
        products = []
        current_name_parts = []
        for ln in product_lines:
            m = re.match(r'^(\d+)\s+(.+)', ln)
            if m:
                # Save previous product
                if current_name_parts:
                    products.append(" ".join(current_name_parts))
                current_name_parts = [m.group(2).strip()]
            else:
                # Continuation of previous product name
                if current_name_parts:
                    current_name_parts.append(ln.strip())
        # Save last product
        if current_name_parts:
            products.append(" ".join(current_name_parts))

        # Also extract other columns that may be concatenated too
        # Build parallel value lists from other concatenated cells
        col_values = {}
        for ci in range(1, len(row_clean)):
            cell = row_clean[ci]
            if "\n" in cell:
                parts = cell.split("\n")
                # Skip header line(s) from the column too
                vals = []
                for p in parts:
                    p = p.strip()
                    if not p:
                        continue
                    # Skip column headers
                    p_lower = p.lower()
                    if any(p_lower.startswith(hw) for hw in _HEADER_WORDS):
                        continue
                    vals.append(p)
                col_values[ci] = vals
            else:
                col_values[ci] = [cell] if cell.strip() else []

        col_map = {}
        for i, h in enumerate(header):
            col_map[h.lower().strip()] = i

        # Create asset for each product
        for pi, product_name in enumerate(products):
            if not product_name or len(product_name) < 2:
                continue
            lower_pn = product_name.lower()
            if any(k in lower_pn for k in ["total", "composição", "composicao", "classe"]):
                continue

            # Build a virtual row for this product index
            virtual_row = [product_name]
            for ci in range(1, len(row_clean)):
                vals = col_values.get(ci, [])
                if pi < len(vals):
                    virtual_row.append(vals[pi])
                else:
                    virtual_row.append("")

            asset = self._parse_row(virtual_row, header, classe, subclasse)
            if asset:
                assets.append(asset)

        return assets

    def _parse_row(self, row: list, header: list, classe: str, subclasse: str) -> Optional[Asset]:
        try:
            nome = row[0]
            if not nome or len(nome) < 2:
                return None

            # Skip date-like names (e.g. "01/01/2025" or "28/09/21")
            if re.match(r'^\d{2}/\d{2}/\d{2,4}$', nome.strip()):
                return None

            # Skip pure number names
            if re.match(r'^[\d.,]+$', nome.strip()):
                return None

            # Skip percentage names (e.g. "100,00%")
            if re.match(r'^[\d.,]+%$', nome.strip()):
                return None

            col_map = {}
            for i, h in enumerate(header):
                col_map[h.lower().strip()] = i

            def get_col(keywords, default=""):
                for kw in keywords:
                    for h, idx in col_map.items():
                        if kw in h:
                            if idx < len(row):
                                return row[idx]
                return default

            taxa_compra = get_col(["taxa de compra"])
            taxa_ano = get_col(["taxa ao ano"])
            data_aplic = get_col(["data de aplicação", "data de aplicacao", "data aplic"])
            valor_principal = get_col(["valor principal"])
            saldo_bruto = get_col(["saldo bruto"])
            saldo_liquido = get_col(["saldo líquido", "saldo liquido"])
            vencimento = get_col(["data de venc", "vencimento"])
            carencia = get_col(["venc. da carência", "carência", "carencia"])

            vb = parse_br(saldo_bruto)
            if vb is None or vb == 0:
                return None

            indexador, taxa = parse_tax_bradesco(taxa_compra, taxa_ano)
            tipo_ativo = classify_asset(nome)
            if tipo_ativo == "Outro":
                tipo_ativo = "Fundo"

            actual_classe = classify_classe(tipo_ativo)
            if actual_classe == "Renda Fixa" and classe:
                actual_classe = classe

            return Asset(
                corretora=BROKER,
                ativo=nome,
                tipo_ativo=tipo_ativo,
                data_aplicacao=parse_date(data_aplic),
                indexador=indexador,
                taxa=taxa,
                vencimento=parse_date(vencimento),
                liquidez=carencia if carencia and carencia.strip() != "-" else None,
                valor_aplicado=parse_br(valor_principal),
                valor_bruto=vb,
                valor_liquido=parse_br(saldo_liquido),
                classe=actual_classe,
                subclasse=subclasse,
            )

        except Exception as e:
            logger.warning(f"Erro ao parsear linha Bradesco: {row} - {e}")
            return None

    @staticmethod
    def _match_subclasse(text: str) -> Optional[str]:
        """Check if text is a subclasse header, return mapped subclasse or None."""
        text = text.strip().lower()
        for key, val in SUBCLASSE_MAP.items():
            if key in text:
                return val
        return None
