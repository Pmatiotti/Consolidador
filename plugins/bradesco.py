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
            _, all_tables = extract_from_pdf(pdf_path)
            assets = self._parse_all(all_tables)
        except Exception as e:
            logger.warning(f"Erro ao processar Bradesco PDF {pdf_path}: {e}")

        return assets

    def _parse_all(self, tables: list) -> List[Asset]:
        assets = []
        current_subclasse = "-"
        current_classe = "Renda Fixa"

        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = [h.lower() for h in header]

            for row in table:
                if not row or not row[0]:
                    continue

                row_clean = [str(c).strip() if c else "" for c in row]
                first_cell = row_clean[0]
                lower_first = first_cell.lower().strip()

                # Detect class headers
                if lower_first in ("renda fixa", "renda variável", "renda variavel"):
                    if "variável" in lower_first or "variavel" in lower_first:
                        current_classe = "Renda Variável"
                    else:
                        current_classe = "Renda Fixa"
                    continue

                # Detect subclasse headers
                matched_sub = self._match_subclasse(lower_first)
                if matched_sub is not None:
                    current_subclasse = matched_sub
                    continue

                # Skip header rows
                if lower_first == "produto" or lower_first == "ativo":
                    continue

                # Skip totals
                if any(k in lower_first for k in ["total", "composição", "composicao", "classe"]):
                    continue

                # Check for multi-line concatenation: PyMuPDF sometimes merges
                # header + product lines into a single cell with \n separators
                # e.g. "Produto\n1 Bradesco Debêntures\nIncentivadas CDI\n2 Bradesco..."
                if "\n" in first_cell and self._is_header_concat(first_cell):
                    embedded = self._extract_from_concat_cell(first_cell, row_clean,
                                                              header, current_classe,
                                                              current_subclasse)
                    assets.extend(embedded)
                    continue

                asset = self._parse_row(row_clean, header, current_classe, current_subclasse)
                if asset:
                    assets.append(asset)

        return assets

    def _is_header_concat(self, cell: str) -> bool:
        """Check if this cell is a header+data concatenation."""
        first_line = cell.split("\n")[0].strip().lower()
        return any(first_line.startswith(hw) for hw in _HEADER_WORDS)

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
