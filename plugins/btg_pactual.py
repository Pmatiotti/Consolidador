"""Plugin para BTG Pactual (ONE Investimentos)."""

import logging
import re
from typing import List, Optional

from models.asset import Asset
from plugins.base import BrokerPlugin
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
from utils.number_parser import parse_br
from utils.tax_parser import parse_tax

logger = logging.getLogger(__name__)

BROKER = "BTG Pactual"


class BTGPactualPlugin(BrokerPlugin):
    @staticmethod
    def detect(text: str) -> bool:
        lower = text.lower()
        if "relatório de performance" not in lower:
            return False
        return "one" in lower or "btg" in lower or "btgpactual" in lower

    @staticmethod
    def broker_name() -> str:
        return BROKER

    def extract(self, pdf_path: str) -> List[Asset]:
        assets = []
        try:
            from utils.pdf_reader import extract_from_pdf
            full_text, all_tables = extract_from_pdf(pdf_path)
            assets = self._parse_all(full_text, all_tables)
        except Exception as e:
            logger.warning(f"Erro ao processar BTG PDF {pdf_path}: {e}")

        return assets

    def _parse_all(self, text: str, tables: list) -> List[Asset]:
        assets = []
        current_section = ""
        current_subclasse = ""

        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = [h.lower() for h in header]

            for row in table[1:]:
                if not row or not row[0]:
                    continue

                row_clean = [str(c).strip() if c else "" for c in row]
                first_cell = row_clean[0].strip()

                # Detect section headers
                lower_first = first_cell.lower()
                if "em renda fixa" in lower_first:
                    current_section = "RF"
                    continue
                if "em coe" in lower_first:
                    current_section = "COE"
                    continue
                if "em fundo de investimento" in lower_first:
                    current_section = "Fundo"
                    continue

                # Detect subclasses
                if any(k in lower_first for k in ["pré-fixado", "prefixado", "pré fixado"]):
                    current_subclasse = "Pré-fixado"
                    continue
                if "pós-fixado" in lower_first or "pós fixado" in lower_first or "pos-fixado" in lower_first:
                    current_subclasse = "Pós-fixado"
                    continue
                if "inflação" in lower_first or "inflacao" in lower_first:
                    current_subclasse = "Inflação"
                    continue
                if "alternativo" in lower_first:
                    current_subclasse = "Alternativo"
                    continue

                # Check for conta corrente
                if "conta corrente" in lower_first or "saldo disponível" in lower_first:
                    val = self._find_value_in_row(row_clean)
                    if val is not None and val > 0:
                        assets.append(Asset(
                            corretora=BROKER,
                            ativo="Conta Corrente BTG",
                            tipo_ativo="Conta Corrente",
                            data_aplicacao=None,
                            indexador="-",
                            taxa=None,
                            vencimento=None,
                            liquidez="D+0",
                            valor_aplicado=None,
                            valor_bruto=val,
                            valor_liquido=val,
                            classe="Conta Corrente",
                            subclasse="-",
                        ))
                    continue

                # Skip summary/total rows
                if any(k in lower_first for k in ["total", "distribuição", "patrimônio"]):
                    continue

                # Try to parse asset rows based on section
                asset = self._parse_asset_row(row_clean, header, current_section, current_subclasse)
                if asset:
                    assets.append(asset)

        return assets

    def _parse_asset_row(self, row: list, header: list, section: str, subclasse: str) -> Optional[Asset]:
        """Parse a single asset row."""
        try:
            nome = row[0] if row else ""
            if not nome or len(nome) < 2:
                return None

            # Map columns by header
            col_map = {}
            for i, h in enumerate(header):
                col_map[h.lower()] = i

            def get_col(keywords, default=""):
                for kw in keywords:
                    for h, idx in col_map.items():
                        if kw in h:
                            if idx < len(row):
                                return row[idx]
                return default

            taxa_raw = get_col(["taxa"])
            data_ini = get_col(["data inicial", "data"])
            vencimento = get_col(["vencimento", "resgate"])
            saldo_bruto = get_col(["saldo bruto", "bruto"])
            saldo_liquido = get_col(["saldo líquido", "líquido"])
            valor_aplicado = get_col(["valor aplicado", "aplicado"])

            valor_bruto = parse_br(saldo_bruto)
            if valor_bruto is None or valor_bruto == 0:
                return None

            indexador, taxa = parse_tax(taxa_raw)
            tipo_ativo = classify_asset(nome)

            if section == "COE":
                classe = "COE"
                subclasse = "Alternativo"
                if tipo_ativo == "Outro":
                    tipo_ativo = "COE"
            elif section == "Fundo":
                classe = "Fundo de Investimento"
                if tipo_ativo == "Outro":
                    tipo_ativo = "Fundo"
                if not subclasse:
                    subclasse = "Multimercado"
            else:
                classe = classify_classe(tipo_ativo)
                if tipo_ativo == "Outro":
                    tipo_ativo = "CDB"  # Default RF

            return Asset(
                corretora=BROKER,
                ativo=nome,
                tipo_ativo=tipo_ativo,
                data_aplicacao=parse_date(data_ini),
                indexador=indexador,
                taxa=taxa,
                vencimento=parse_date(vencimento),
                liquidez=None,
                valor_aplicado=parse_br(valor_aplicado),
                valor_bruto=valor_bruto,
                valor_liquido=parse_br(saldo_liquido),
                classe=classe,
                subclasse=subclasse if subclasse else "-",
            )

        except Exception as e:
            logger.warning(f"Erro ao parsear linha BTG: {row} - {e}")
            return None

    def _find_value_in_row(self, row: list) -> Optional[float]:
        """Find the first parseable monetary value in a row."""
        for cell in row[1:]:
            val = parse_br(cell)
            if val is not None and val > 0:
                return val
        return None
