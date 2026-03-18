"""Plugin para XP Investimentos — herda de Monte Bravo (plataforma compartilhada)."""

import logging
import re
from typing import List, Optional

import pdfplumber

from models.asset import Asset
from plugins.base import BrokerPlugin
from plugins.monte_bravo import MonteBravoPlugin
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
from utils.number_parser import parse_br
from utils.tax_parser import parse_tax

logger = logging.getLogger(__name__)

BROKER = "XP"


class XPPlugin(MonteBravoPlugin):
    """XP usa mesma plataforma que Monte Bravo, com extensões para Previdência e COE."""

    @staticmethod
    def detect(text: str) -> bool:
        lower = text.lower()
        # NÃO pode ser Monte Bravo
        if "montebravo" in lower or "monte bravo" in lower:
            return False
        return "xp investimentos" in lower or "xp" in lower

    @staticmethod
    def broker_name() -> str:
        return BROKER

    def extract(self, pdf_path: str) -> List[Asset]:
        assets = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_text = ""
                all_tables = []
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    full_text += text + "\n"
                    tables = page.extract_tables()
                    for table in tables:
                        all_tables.append(table)

                # Use base Monte Bravo parsing
                assets = self._parse_all(full_text, all_tables)

                # Also parse XP-specific sections
                assets.extend(self._parse_previdencia(all_tables))
                assets.extend(self._parse_coe(all_tables))

        except Exception as e:
            logger.warning(f"Erro ao processar XP PDF {pdf_path}: {e}")

        # Fix broker name (inherited parse uses Monte Bravo)
        for asset in assets:
            asset.corretora = BROKER

        return assets

    def _parse_all(self, text: str, tables: list) -> List[Asset]:
        """Override to handle XP-specific fund subclasses."""
        assets = super()._parse_all(text, tables)

        # Reclassify fund subclasses for XP
        for asset in assets:
            upper_name = asset.ativo.upper()
            if asset.tipo_ativo == "Fundo" or asset.classe == "Fundo de Investimento":
                if "RENDA FIXA" in upper_name or "RF PÓS" in upper_name or "FIRF" in upper_name:
                    asset.subclasse = "Fundos RF Pós"
                elif "MULTIMERCADO" in upper_name or "MULTI" in upper_name:
                    asset.subclasse = "Fundos Multimercado"
                elif "ALTERNATIV" in upper_name:
                    asset.subclasse = "Fundos Alternativos"
                elif "FIAGRO" in upper_name:
                    asset.subclasse = "Fundos Alternativos"

        return assets

    def _parse_previdencia(self, tables: list) -> List[Asset]:
        """Parse seção Previdência Privada (específica XP)."""
        assets = []
        in_previdencia = False

        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = " ".join(header).lower()

            # Detect previdência section
            if "plano" in header_lower and "tributação" in header_lower:
                in_previdencia = True

            if not in_previdencia:
                # Check text in rows for section detection
                for row in table:
                    if row and row[0]:
                        if "previdência" in str(row[0]).lower():
                            in_previdencia = True
                            break

            if not in_previdencia:
                continue

            col_map = self._build_col_map(header)

            for row in table[1:]:
                if not row or not row[0]:
                    continue

                row_clean = [str(c).strip() if c else "" for c in row]
                nome = row_clean[0]
                if not nome or len(nome) < 3:
                    continue
                if nome.lower() == "ativo":
                    continue

                # Skip totals
                if any(k in nome.lower() for k in ["total", "patrimônio"]):
                    continue

                posicao = self._get_col(row_clean, col_map, ["posição", "posicao"])
                plano = self._get_col(row_clean, col_map, ["plano"])

                vb = parse_br(posicao)
                if vb is None or vb == 0:
                    continue

                plano_upper = plano.upper().strip()
                if "PGBL" in plano_upper:
                    subclasse = "Previdência PGBL"
                else:
                    subclasse = "Previdência VGBL"

                assets.append(Asset(
                    corretora=BROKER,
                    ativo=nome,
                    tipo_ativo="Previdência",
                    data_aplicacao=None,
                    indexador="-",
                    taxa=None,
                    vencimento=None,
                    liquidez=None,
                    valor_aplicado=None,
                    valor_bruto=vb,
                    valor_liquido=None,  # XP: valor_liquido = "-"
                    classe="Previdência",
                    subclasse=subclasse,
                ))

            in_previdencia = False

        return assets

    def _parse_coe(self, tables: list) -> List[Asset]:
        """Parse seção COE (específica XP)."""
        assets = []

        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = " ".join(header).lower()

            # COE table: has "emissor" and "preço" columns
            if "emissor" not in header_lower:
                continue

            col_map = self._build_col_map(header)

            for row in table[1:]:
                if not row or not row[0]:
                    continue

                row_clean = [str(c).strip() if c else "" for c in row]
                nome = row_clean[0]
                if not nome or len(nome) < 3:
                    continue
                if nome.lower() == "ativo":
                    continue
                if any(k in nome.lower() for k in ["total", "patrimônio"]):
                    continue

                posicao = self._get_col(row_clean, col_map, ["posição", "posicao"])
                data_aplic = self._get_col(row_clean, col_map, ["data aplicação", "data aplic"])
                vencimento = self._get_col(row_clean, col_map, ["vencimento"])

                vb = parse_br(posicao)
                if vb is None or vb == 0:
                    continue

                assets.append(Asset(
                    corretora=BROKER,
                    ativo=nome,
                    tipo_ativo="COE",
                    data_aplicacao=parse_date(data_aplic),
                    indexador="Alternativo",
                    taxa=None,
                    vencimento=parse_date(vencimento),
                    liquidez=None,
                    valor_aplicado=parse_br(self._get_col(row_clean, col_map, ["valor aplicado"])),
                    valor_bruto=vb,
                    valor_liquido=vb,
                    classe="COE",
                    subclasse="Alternativo",
                ))

        return assets
