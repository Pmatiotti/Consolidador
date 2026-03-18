"""Plugin para Itaú Personnalité — O mais complexo."""

import logging
import re
from typing import List, Optional

import pdfplumber

from models.asset import Asset
from plugins.base import BrokerPlugin
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
from utils.number_parser import parse_br
from utils.tax_parser import parse_tax

logger = logging.getLogger(__name__)

BROKER = "Itaú"

# Mapeamento subclasse Itaú → padrão
SUBCLASSE_MAP = {
    "juros pós-fixados": "Pós-fixado",
    "juros pos-fixados": "Pós-fixado",
    "juros pós fixados": "Pós-fixado",
    "pós-fixados": "Pós-fixado",
    "juros prefixados": "Pré-fixado",
    "prefixados": "Pré-fixado",
    "inflação": "Inflação",
    "inflacao": "Inflação",
    "multimercados": "Multimercado",
    "multimercado": "Multimercado",
    "ações": "Renda Variável",
    "acoes": "Renda Variável",
}

# Linhas que devem ser ignoradas (rentabilidade, não ativos)
SKIP_PATTERNS = [
    "% do cdi", "% do ibovespa", "retorno sobre o ifix",
    "retorno sobre o ipca", "retorno sobre", "% cdi",
    "total da carteira", "total",
]


class ItauPlugin(BrokerPlugin):
    @staticmethod
    def detect(text: str) -> bool:
        lower = text.lower()
        has_itau = "itaú" in lower or "itau" in lower or "personnalité" in lower or "personnalite" in lower
        has_carteira = "carteira de investimentos" in lower
        return has_itau and has_carteira

    @staticmethod
    def broker_name() -> str:
        return BROKER

    def extract(self, pdf_path: str) -> List[Asset]:
        assets = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                all_tables = []
                full_text = ""
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    full_text += text + "\n"
                    tables = page.extract_tables()
                    for table in tables:
                        all_tables.append(table)

                assets = self._parse_all(full_text, all_tables)
        except Exception as e:
            logger.warning(f"Erro ao processar Itaú PDF {pdf_path}: {e}")

        return assets

    def _parse_all(self, text: str, tables: list) -> List[Asset]:
        assets = []
        current_subclasse = "-"
        in_carteira_detalhada = False

        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = " ".join(header).lower()

            # Detect "sua carteira detalhada" section
            if "produto" in header_lower and "saldo" in header_lower:
                in_carteira_detalhada = True

            if not in_carteira_detalhada:
                continue

            col_map = {}
            for i, h in enumerate(header):
                col_map[h.lower().strip()] = i

            for row in table[1:]:
                if not row or not row[0]:
                    continue

                row_clean = [str(c).strip() if c else "" for c in row]
                first_cell = row_clean[0]
                lower_first = first_cell.lower().strip()

                # Skip empty
                if not lower_first:
                    continue

                # Check if this is a section header (e.g., "48,8% Juros pós-fixados")
                section = self._detect_section_header(lower_first)
                if section:
                    current_subclasse = section
                    continue

                # Skip benchmark/return lines
                if self._is_skip_line(lower_first):
                    continue

                # Skip "Total da Carteira" and other totals
                if "total" in lower_first:
                    continue

                # Parse asset
                asset = self._parse_asset_row(row_clean, col_map, current_subclasse)
                if asset:
                    assets.append(asset)

        return assets

    def _parse_asset_row(self, row: list, col_map: dict, subclasse: str) -> Optional[Asset]:
        try:
            nome = row[0]
            if not nome or len(nome) < 2:
                return None

            def get_col(keywords, default=""):
                for kw in keywords:
                    for h, idx in col_map.items():
                        if kw in h:
                            if idx < len(row):
                                return row[idx]
                return default

            saldo = get_col(["saldo"])
            aplic = get_col(["aplic"])
            vencto = get_col(["vencto", "venc"])
            taxa_raw = get_col(["taxa contrat", "taxa"])

            vb = parse_br(saldo)
            if vb is None or vb == 0:
                return None

            indexador, taxa = parse_tax(taxa_raw)
            tipo_ativo = classify_asset(nome)

            # Reclassificação especial Itaú
            upper_name = nome.upper()

            # COE na seção Ações
            if any(k in upper_name for k in ["GANHO GARANTI", "NASDAQ", "SP 500"]):
                tipo_ativo = "COE"
                classe = "COE"
                subclasse = "Alternativo"
            # FII
            elif tipo_ativo == "FII":
                classe = "Renda Variável"
                subclasse = "Renda Variável"
            # Previdência
            elif tipo_ativo == "Previdência":
                classe = "Previdência"
                if "VGBL" in upper_name:
                    subclasse = "Previdência VGBL"
                elif "PGBL" in upper_name:
                    subclasse = "Previdência PGBL"
                else:
                    subclasse = "Previdência VGBL"
            # Fundos
            elif tipo_ativo == "Fundo":
                classe = "Fundo de Investimento"
                # Keep inherited subclasse from section
            elif tipo_ativo == "Outro":
                tipo_ativo = "CDB"
                classe = "Renda Fixa"
            else:
                classe = classify_classe(tipo_ativo)

            # For non-special types, use section subclasse
            if tipo_ativo not in ("COE", "FII", "Previdência"):
                if classe not in ("COE", "Previdência"):
                    pass  # keep subclasse from section

            # Sem taxa → inferir indexador da subclasse
            if indexador == "-" and taxa is None:
                if subclasse == "Pós-fixado":
                    indexador = "% CDI"
                elif subclasse == "Pré-fixado":
                    indexador = "Prefixado"
                elif subclasse == "Inflação":
                    indexador = "IPCA +"

            return Asset(
                corretora=BROKER,
                ativo=nome,
                tipo_ativo=tipo_ativo,
                data_aplicacao=parse_date(aplic) if aplic and aplic != "-" else None,
                indexador=indexador,
                taxa=taxa,
                vencimento=parse_date(vencto) if vencto and vencto != "-" else None,
                liquidez=None,
                valor_aplicado=None,  # Itaú não tem valor aplicado individual
                valor_bruto=vb,
                valor_liquido=None,   # Itaú não tem valor líquido por ativo
                classe=classe if 'classe' in dir() else classify_classe(tipo_ativo),
                subclasse=subclasse,
            )

        except Exception as e:
            logger.warning(f"Erro ao parsear linha Itaú: {row} - {e}")
            return None

    @staticmethod
    def _detect_section_header(text: str) -> Optional[str]:
        """Detect section header like '48,8% Juros pós-fixados'."""
        for key, val in SUBCLASSE_MAP.items():
            if key in text:
                return val
        return None

    @staticmethod
    def _is_skip_line(text: str) -> bool:
        """Check if line should be skipped (benchmark lines)."""
        for pattern in SKIP_PATTERNS:
            if text.startswith(pattern):
                return True
        return False
