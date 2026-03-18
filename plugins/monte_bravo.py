"""Plugin para Monte Bravo."""

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

BROKER = "Monte Bravo"


class MonteBravoPlugin(BrokerPlugin):
    @staticmethod
    def detect(text: str) -> bool:
        lower = text.lower()
        has_mb = "montebravo" in lower or "monte bravo" in lower
        has_rf = "precificação de renda fixa" in lower or "precificacao de renda fixa" in lower
        return has_mb and has_rf

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
            logger.warning(f"Erro ao processar Monte Bravo PDF {pdf_path}: {e}")

        return assets

    def _parse_all(self, text: str, tables: list) -> List[Asset]:
        assets = []
        current_subclasse = ""
        current_section = "RF"

        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = " ".join(header).lower()

            # Detect section type by header content
            if "data cota" in header_lower or "valor cota" in header_lower or "qtd cotas" in header_lower:
                current_section = "Fundo"

            for row in table:
                if not row or not row[0]:
                    continue

                row_clean = [str(c).strip() if c else "" for c in row]
                first_cell = row_clean[0]
                lower_first = first_cell.lower()

                # Detect subclasse from section headers
                if "prefixada" in lower_first or "pré-fixada" in lower_first:
                    current_subclasse = "Pré-fixado"
                    continue
                if "pós-fixada" in lower_first or "pos-fixada" in lower_first:
                    current_subclasse = "Pós-fixado"
                    continue
                if "inflação" in lower_first or "inflacao" in lower_first:
                    current_subclasse = "Inflação"
                    continue
                if "fundos alternativos" in lower_first:
                    current_subclasse = "Fundos Alternativos"
                    current_section = "Fundo"
                    continue
                if "fundos de investimento" in lower_first or "fundo de investimento" in lower_first:
                    current_section = "Fundo"
                    current_subclasse = "Multimercado"
                    continue

                # Skip header rows
                if lower_first == "ativo" or "saldo projetado" in lower_first:
                    continue

                # Check saldo disponível
                if "saldo disponível" in lower_first or "saldo disponivel" in lower_first:
                    val = self._find_value_in_row(row_clean)
                    if val is not None and val > 0:
                        assets.append(Asset(
                            corretora=self.broker_name(),
                            ativo="Conta Corrente " + self.broker_name(),
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

                # Skip totals
                if any(k in lower_first for k in ["total", "patrimônio", "patrimonio"]):
                    continue

                # Try to parse asset
                if current_section == "Fundo":
                    asset = self._parse_fundo_row(row_clean, header)
                    if asset:
                        asset.subclasse = current_subclasse if current_subclasse else "Multimercado"
                        assets.append(asset)
                else:
                    asset = self._parse_rf_row(row_clean, header, current_subclasse)
                    if asset:
                        assets.append(asset)

        return assets

    def _parse_rf_row(self, row: list, header: list, subclasse: str) -> Optional[Asset]:
        """Parse RF row: Ativo | Aplicação | Carência | Vencimento | Taxa De Compra | ... """
        try:
            nome = row[0]
            if not nome or len(nome) < 2:
                return None

            col_map = self._build_col_map(header)

            taxa_raw = self._get_col(row, col_map, ["taxa de compra", "taxa"])
            aplicacao = self._get_col(row, col_map, ["aplicação", "aplicacao", "aplic"])
            carencia = self._get_col(row, col_map, ["carência", "carencia"])
            vencimento = self._get_col(row, col_map, ["vencimento"])
            valor_aplicado = self._get_col(row, col_map, ["valor aplicado"])
            posicao = self._get_col(row, col_map, ["posição taxa de compra", "posição", "posicao"])
            valor_liquido = self._get_col(row, col_map, ["valor líquido", "valor liquido", "líquido"])

            vb = parse_br(posicao)
            if vb is None:
                vb = parse_br(valor_aplicado)
            if vb is None or vb == 0:
                return None

            indexador, taxa = parse_tax(taxa_raw)
            tipo_ativo = classify_asset(nome)
            if tipo_ativo == "Outro":
                tipo_ativo = "CDB"

            return Asset(
                corretora=self.broker_name(),
                ativo=nome,
                tipo_ativo=tipo_ativo,
                data_aplicacao=parse_date(aplicacao),
                indexador=indexador,
                taxa=taxa,
                vencimento=parse_date(vencimento),
                liquidez=carencia if carencia and carencia != "-" else None,
                valor_aplicado=parse_br(valor_aplicado),
                valor_bruto=vb,
                valor_liquido=parse_br(valor_liquido),
                classe=classify_classe(tipo_ativo),
                subclasse=subclasse if subclasse else "-",
            )
        except Exception as e:
            logger.warning(f"Erro ao parsear linha RF Monte Bravo: {row} - {e}")
            return None

    def _parse_fundo_row(self, row: list, header: list) -> Optional[Asset]:
        """Parse Fund row: Ativo | Data Cota | Valor Cota | Qtd Cotas | Em Cotização | Posição | Valor Líquido"""
        try:
            nome = row[0]
            if not nome or len(nome) < 2:
                return None

            col_map = self._build_col_map(header)

            posicao = self._get_col(row, col_map, ["posição", "posicao"])
            valor_liquido = self._get_col(row, col_map, ["valor líquido", "valor liquido", "líquido"])

            vb = parse_br(posicao)
            if vb is None:
                vb = parse_br(valor_liquido)
            if vb is None or vb == 0:
                return None

            tipo_ativo = classify_asset(nome)
            if tipo_ativo == "Outro":
                tipo_ativo = "Fundo"

            return Asset(
                corretora=self.broker_name(),
                ativo=nome,
                tipo_ativo=tipo_ativo,
                data_aplicacao=None,
                indexador="-",
                taxa=None,
                vencimento=None,
                liquidez=None,
                valor_aplicado=None,
                valor_bruto=vb,
                valor_liquido=parse_br(valor_liquido),
                classe=classify_classe(tipo_ativo),
                subclasse="Multimercado",
            )
        except Exception as e:
            logger.warning(f"Erro ao parsear linha Fundo Monte Bravo: {row} - {e}")
            return None

    @staticmethod
    def _build_col_map(header: list) -> dict:
        col_map = {}
        for i, h in enumerate(header):
            col_map[h.lower().strip()] = i
        return col_map

    @staticmethod
    def _get_col(row: list, col_map: dict, keywords: list, default: str = "") -> str:
        for kw in keywords:
            for h, idx in col_map.items():
                if kw in h:
                    if idx < len(row):
                        return row[idx]
        return default

    @staticmethod
    def _find_value_in_row(row: list) -> Optional[float]:
        for cell in row[1:]:
            val = parse_br(cell)
            if val is not None and val > 0:
                return val
        return None
