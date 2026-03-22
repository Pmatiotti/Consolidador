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

            header_raw = [str(c).strip() if c else "" for c in table[0]]
            header_upper = [h.upper() for h in header_raw]

            # SKIP summary tables — they have "CLASSE DO ATIVO" in header
            if any("CLASSE" in h for h in header_upper):
                continue

            # Only use detail tables — must have "ATIVO" in header
            has_ativo = any(h == "ATIVO" for h in header_upper)
            if not has_ativo:
                continue

            # Build column map from header names
            col_map = self._build_col_map(header_raw)
            logger.debug(f"BB table header: {header_raw}")
            logger.debug(f"BB col_map: {col_map}")

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

                asset = self._parse_row(row_clean, col_map,
                                        current_classe, current_subclasse)
                if asset:
                    assets.append(asset)

        return assets

    def _parse_row(self, row: list, col_map: dict,
                   classe: str, subclasse: str) -> Optional[Asset]:
        """Parse BB detail row using header-based column mapping.

        BB detail tables have columns like:
        Ativo | Saldo Bruto Anterior | Entradas | Saídas |
        Saldo Bruto Atual | (ghost) | Provisão IR/IOF |
        Saldo Líquido | Participação %
        """
        try:
            # Find the name — first non-empty cell
            nome = ""
            for cell in row:
                if cell and len(cell) >= 2 and not cell.replace('.', '').replace(',', '').replace('-', '').isdigit():
                    nome = cell
                    break

            if not nome or len(nome) < 2:
                return None

            # Use header-based column mapping to find bruto and líquido
            saldo_bruto = None
            saldo_liquido = None

            # Try by header name — "saldo bruto atual" or "bruto atual"
            bruto_str = self._get_col(row, col_map,
                                       ["saldo bruto atual", "bruto atual",
                                        "sld bruto atual", "sld. bruto atual"])
            if bruto_str:
                saldo_bruto = parse_br(bruto_str)

            # If header mapping didn't work, try positional approach
            # but ONLY use columns AFTER "saídas" column
            if saldo_bruto is None:
                saidas_idx = self._find_col_idx(col_map, ["saídas", "saidas"])
                # Bruto is the first big number AFTER saídas
                start_idx = (saidas_idx + 1) if saidas_idx is not None else 1
                for i in range(start_idx, len(row)):
                    val = parse_br(row[i])
                    if val is not None and val > 0:
                        saldo_bruto = val
                        break

            # Líquido by header
            liq_str = self._get_col(row, col_map,
                                     ["saldo líquido", "saldo liquido",
                                      "sld líquido", "sld. líquido",
                                      "sld liquido", "sld. liquido"])
            if liq_str:
                saldo_liquido = parse_br(liq_str)

            # Líquido positional fallback: last big number before participação
            if saldo_liquido is None and saldo_bruto is not None:
                part_idx = self._find_col_idx(col_map, ["participação", "participacao", "partic"])
                end_idx = (part_idx) if part_idx is not None else len(row)
                # Work backwards from end to find líquido
                for i in range(end_idx - 1, 0, -1):
                    val = parse_br(row[i])
                    if val is not None and val > 0 and val != saldo_bruto:
                        saldo_liquido = val
                        break

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
    def _find_col_idx(col_map: dict, keywords: list) -> Optional[int]:
        for kw in keywords:
            for h, idx in col_map.items():
                if kw in h:
                    return idx
        return None
