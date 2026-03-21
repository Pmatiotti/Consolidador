"""Plugin para Banco do Brasil — Portfólio de Investimentos."""

import logging
import re
from typing import List, Optional

from models.asset import Asset
from plugins.base import BrokerPlugin
from utils.asset_classifier import classify_asset, classify_classe
from utils.number_parser import parse_br

logger = logging.getLogger(__name__)

BROKER = "Banco do Brasil"

# Mapeamento de seção (resumo página 3) → subclasse
SUBCLASSE_MAP = {
    "pós cdi": "Pós-fixado",
    "pos cdi": "Pós-fixado",
    "pós-fixado": "Pós-fixado",
    "inflação": "Inflação",
    "inflacao": "Inflação",
    "multimercado": "Multimercado",
    "multimercados": "Multimercado",
    "renda variável": "Renda Variável",
    "renda variavel": "Renda Variável",
    "prefixado": "Pré-fixado",
    "pré-fixado": "Pré-fixado",
}


class BancoDBrasilPlugin(BrokerPlugin):
    @staticmethod
    def detect(text: str) -> bool:
        lower = text.lower()
        if "bb.com.br/investimentos" in lower:
            return True
        return "portfólio de investimentos" in lower and "agência/conta" in lower

    @staticmethod
    def broker_name() -> str:
        return BROKER

    def extract(self, pdf_path: str) -> List[Asset]:
        assets = []
        try:
            from utils.pdf_reader import extract_from_pdf
            full_text, all_tables = extract_from_pdf(pdf_path)
            assets = self._parse_all(all_tables)
        except Exception as e:
            logger.warning(f"Erro ao processar BB PDF {pdf_path}: {e}")
        return assets

    def _parse_all(self, tables: list) -> List[Asset]:
        assets = []
        current_subclasse = "-"
        current_classe = "Renda Fixa"

        for table in tables:
            if not table or not table[0]:
                continue

            for row in table:
                if not row or not row[0]:
                    continue

                row_clean = [str(c).strip() if c else "" for c in row]
                first_cell = row_clean[0]
                lower_first = first_cell.lower().strip()

                # Detect class/subclass headers
                matched_sub = self._match_subclasse(lower_first)
                if matched_sub is not None:
                    current_subclasse = matched_sub
                    if "renda variável" in lower_first or "renda variavel" in lower_first:
                        current_classe = "Renda Variável"
                    elif "multimercado" in lower_first:
                        current_classe = "Fundo de Investimento"
                    else:
                        current_classe = "Renda Fixa"
                    continue

                # Skip header rows
                if lower_first in ("ativo", "produto", ""):
                    continue
                if any(k in lower_first for k in ["saldo bruto", "entradas",
                                                   "saídas", "saidas",
                                                   "participação", "participacao",
                                                   "provisão", "provisao"]):
                    continue

                # Skip totals
                if any(k in lower_first for k in ["total", "subtotal"]):
                    continue

                asset = self._parse_row(row_clean, current_classe, current_subclasse)
                if asset:
                    assets.append(asset)

        return assets

    def _parse_row(self, row: list, classe: str, subclasse: str) -> Optional[Asset]:
        """Parse BB row.

        Table columns (9-10 cols):
        [0] Nome | [1] Saldo bruto anterior (IGNORAR) | [2] Entradas (IGNORAR)
        [3] Saídas (IGNORAR) | [4] Saldo Bruto atual | [5] Vazio/None
        [6] Provisão IR/IOF | [7] Saldo Líquido | [8] Participação %
        """
        try:
            nome = row[0]
            if not nome or len(nome) < 2:
                return None

            # Find saldo_bruto and saldo_liquido by position
            # We need to find the right columns - look for numeric values
            # Col 4 = saldo bruto atual, Col 7 = saldo líquido
            saldo_bruto = None
            saldo_liquido = None

            if len(row) >= 9:
                # Standard 9-column layout
                saldo_bruto = parse_br(row[4])
                saldo_liquido = parse_br(row[7])
            elif len(row) >= 8:
                saldo_bruto = parse_br(row[4])
                saldo_liquido = parse_br(row[6])
            else:
                # Try to find largest values in the row
                values = []
                for i, cell in enumerate(row[1:], 1):
                    val = parse_br(cell)
                    if val is not None and val > 0:
                        values.append((i, val))
                if values:
                    # Take the last two big values
                    big_vals = [(i, v) for i, v in values if v > 100]
                    if len(big_vals) >= 2:
                        saldo_bruto = big_vals[-2][1]
                        saldo_liquido = big_vals[-1][1]
                    elif len(big_vals) == 1:
                        saldo_bruto = big_vals[0][1]

            if not saldo_bruto or saldo_bruto == 0:
                return None

            tipo_ativo = classify_asset(nome)
            if tipo_ativo == "Outro":
                # Infer from classe/subclasse
                upper = nome.upper()
                if any(k in upper for k in ["FIA", "FI RF", "FI MULT", "FIF",
                                            "AÇÕES", "ACOES", "PVT FI",
                                            "FI RENDA"]):
                    tipo_ativo = "Fundo"
                elif subclasse == "Renda Variável":
                    tipo_ativo = "FII"
                else:
                    tipo_ativo = "Fundo"

            actual_classe = classify_classe(tipo_ativo)
            if classe and actual_classe == "Renda Fixa":
                actual_classe = classe

            return Asset(
                corretora=BROKER,
                ativo=nome,
                tipo_ativo=tipo_ativo,
                data_aplicacao=None,
                indexador="-",
                taxa=None,
                vencimento=None,
                liquidez=None,
                valor_aplicado=None,
                valor_bruto=saldo_bruto,
                valor_liquido=saldo_liquido,
                classe=actual_classe,
                subclasse=subclasse,
            )
        except Exception as e:
            logger.warning(f"Erro ao parsear linha BB: {row} - {e}")
            return None

    @staticmethod
    def _match_subclasse(text: str) -> Optional[str]:
        text = text.strip().lower()
        for key, val in SUBCLASSE_MAP.items():
            if key in text:
                return val
        return None
