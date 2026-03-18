"""Plugin para Bradesco Principal."""

import logging
import re
from typing import List, Optional

import pdfplumber

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
            with pdfplumber.open(pdf_path) as pdf:
                all_tables = []
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        all_tables.append(table)

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

                asset = self._parse_row(row_clean, header, current_classe, current_subclasse)
                if asset:
                    assets.append(asset)

        return assets

    def _parse_row(self, row: list, header: list, classe: str, subclasse: str) -> Optional[Asset]:
        try:
            nome = row[0]
            if not nome or len(nome) < 2:
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
