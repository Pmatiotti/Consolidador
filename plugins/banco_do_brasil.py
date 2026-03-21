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

# Mapeamento de seção → subclasse
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

            header = [str(c).strip().upper() if c else "" for c in table[0]]

            # SKIP summary tables — they have "CLASSE DO ATIVO" in header
            if any("CLASSE" in h for h in header):
                continue

            # Only use detail tables — must have "ATIVO" in header
            has_ativo = any(h == "ATIVO" for h in header)
            if not has_ativo:
                # Also try to detect by column count + known patterns
                # Some BB detail tables start with empty header row
                continue

            # Determine column layout (9 or 10 cols, ghost column possible)
            ncols = len(header)

            for row in table[1:]:
                if not row:
                    continue

                row_clean = [str(c).strip() if c else "" for c in row]

                # Find the name — first non-empty cell
                nome = ""
                nome_idx = -1
                for ci, cell in enumerate(row_clean):
                    if cell and len(cell) >= 2:
                        nome = cell
                        nome_idx = ci
                        break

                if not nome:
                    continue

                lower_nome = nome.lower().strip()

                # Detect class/subclass headers
                matched_sub = self._match_subclasse(lower_nome)
                if matched_sub is not None:
                    current_subclasse = matched_sub
                    if "renda variável" in lower_nome or "renda variavel" in lower_nome:
                        current_classe = "Renda Variável"
                    elif "multimercado" in lower_nome:
                        current_classe = "Fundo de Investimento"
                    else:
                        current_classe = "Renda Fixa"
                    continue

                # Skip header/total/metadata rows
                if lower_nome in ("ativo", "produto", ""):
                    continue
                if any(k in lower_nome for k in ["saldo bruto", "entradas",
                                                   "saídas", "saidas",
                                                   "participação", "participacao",
                                                   "provisão", "provisao",
                                                   "total", "subtotal",
                                                   "carteira", "classe"]):
                    continue

                asset = self._parse_row(row_clean, nome_idx, ncols,
                                        current_classe, current_subclasse)
                if asset:
                    assets.append(asset)

        return assets

    def _parse_row(self, row: list, nome_idx: int, ncols: int,
                   classe: str, subclasse: str) -> Optional[Asset]:
        """Parse BB detail row.

        BB detail tables have 9 or 10 columns:
        Layout (typical):
        [0] Nome | [1] Saldo bruto anterior | [2] Entradas | [3] Saídas
        [4] Saldo Bruto Atual | [5] ghost/empty | [6] Provisão IR/IOF
        [7] Saldo Líquido | [8] Participação %

        With ghost column (10 cols): same but shifted — bruto at col 5,
        líquido at col 7 or 8.
        """
        try:
            nome = row[nome_idx]
            if not nome or len(nome) < 2:
                return None

            # Extract all numeric values from the row (after nome)
            num_values = []
            for i in range(nome_idx + 1, len(row)):
                val = parse_br(row[i])
                if val is not None:
                    num_values.append((i, val))

            if not num_values:
                return None

            # Strategy: find saldo_bruto and saldo_liquido by position
            # Saldo bruto = col 4 or 5 (depending on ghost col)
            # Saldo líquido = col 7 or 8
            saldo_bruto = None
            saldo_liquido = None

            if len(row) >= 9:
                # Try standard positions first
                # Bruto: col 4 (or 5 if ghost col)
                bruto_candidates = [4, 5]
                for bc in bruto_candidates:
                    if bc < len(row):
                        val = parse_br(row[bc])
                        if val is not None and val > 0:
                            saldo_bruto = val
                            break

                # Líquido: col 7 or 8
                liq_candidates = [7, 8]
                for lc in liq_candidates:
                    if lc < len(row):
                        val = parse_br(row[lc])
                        if val is not None and val > 0:
                            saldo_liquido = val
                            break
            else:
                # Short row — take the biggest values
                big_vals = [(i, v) for i, v in num_values if v > 100]
                if len(big_vals) >= 2:
                    saldo_bruto = big_vals[-2][1]
                    saldo_liquido = big_vals[-1][1]
                elif len(big_vals) == 1:
                    saldo_bruto = big_vals[0][1]

            if not saldo_bruto or saldo_bruto == 0:
                return None

            tipo_ativo = classify_asset(nome)
            if tipo_ativo == "Outro":
                upper = nome.upper()
                if any(k in upper for k in ["FIA", "FI RF", "FI MULT", "FIF",
                                            "AÇÕES", "ACOES", "PVT FI",
                                            "FI RENDA", "FUNDO"]):
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
