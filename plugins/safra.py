"""Plugin para Banco Safra — Relatório Mensal."""

import logging
import re
from typing import Dict, List, Optional, Tuple

from models.asset import Asset
from plugins.base import BrokerPlugin
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
from utils.number_parser import parse_br

logger = logging.getLogger(__name__)

BROKER = "Safra"

# Classes que são headers (não ativos) na tabela de posição
CLASS_HEADERS = {
    "renda fixa", "previdência", "previdencia",
    "renda variável", "renda variavel",
    "ações", "acoes", "total",
}


class SafraPlugin(BrokerPlugin):
    @staticmethod
    def detect(text: str) -> bool:
        lower = text.lower()
        has_relatorio = "relatório mensal" in lower or "relatorio mensal" in lower
        has_safra = "safra" in lower or "safrabm" in lower or "agência: 28800" in lower
        return has_relatorio and has_safra

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
            logger.warning(f"Erro ao processar Safra PDF {pdf_path}: {e}")
        return assets

    def _parse_all(self, tables: list) -> List[Asset]:
        # Parse detail tables first (have full data)
        detail_assets = self._parse_detail_rf(tables)
        detail_funds = self._parse_detail_fundos(tables)
        detail_acoes = self._parse_detail_acoes(tables)

        # Combine all
        assets = detail_assets + detail_funds + detail_acoes

        # If detail tables found assets, use those
        if assets:
            return assets

        # Fallback: use summary table (Posição de Investimentos)
        return self._parse_summary(tables)

    # ------------------------------------------------------------------
    # Detail RF table (page 12): full data with taxa
    # ------------------------------------------------------------------
    def _parse_detail_rf(self, tables: list) -> List[Asset]:
        """Parse Detalhamento RF table.

        Columns: Ativo | Emissor/Devedor | Indexador | %Indexador | Taxa a.a |
                 Data aplicação | Vencimento | Quantidade | Sld. Aplicado |
                 Sld. Bruto | Impostos | Sld. Líquido
        """
        assets = []
        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = " ".join(header).lower()

            # Identify RF detail table by having both "indexador" and "taxa"
            if "indexador" not in header_lower or "taxa" not in header_lower:
                continue
            if "emissor" not in header_lower and "devedor" not in header_lower:
                continue

            col_map = self._build_col_map(header)

            for row in table[1:]:
                if not row or not row[0]:
                    continue
                row_clean = [str(c).strip() if c else "" for c in row]
                nome = row_clean[0]
                if not nome or len(nome) < 2:
                    continue
                lower_nome = nome.lower()
                if lower_nome in CLASS_HEADERS or "total" in lower_nome:
                    continue
                if lower_nome == "ativo":
                    continue
                # Skip date-like names (movimentação rows)
                if re.match(r'^\d{2}/\d{2}/\d{2,4}$', nome.strip()):
                    continue

                asset = self._parse_detail_rf_row(row_clean, col_map)
                if asset:
                    assets.append(asset)

        return assets

    def _parse_detail_rf_row(self, row: list, col_map: dict) -> Optional[Asset]:
        try:
            nome = row[0]
            emissor = self._get_col(row, col_map, ["emissor", "devedor"])
            indexador_raw = self._get_col(row, col_map, ["indexador"])
            pct_index = self._get_col(row, col_map, ["%indexador", "% indexador"])
            taxa_aa = self._get_col(row, col_map, ["taxa a.a", "taxa"])
            data_aplic = self._get_col(row, col_map, ["data aplicação", "data aplicacao", "aplicação"])
            vencimento = self._get_col(row, col_map, ["vencimento", "repactuação"])
            saldo_aplicado = self._get_col(row, col_map, ["sld. aplicado", "aplicado"])
            saldo_bruto = self._get_col(row, col_map, ["sld. bruto", "bruto"])
            saldo_liquido = self._get_col(row, col_map, ["sld. líquido", "sld. liquido", "líquido"])

            vb = parse_br(saldo_bruto)
            if vb is None or vb == 0:
                return None

            # Parse taxa Safra
            indexador, taxa = self._parse_taxa_safra(indexador_raw, pct_index, taxa_aa)

            # Build full name
            full_name = f"{nome} - {emissor}" if emissor and emissor != "-" else nome

            tipo_ativo = classify_asset(full_name)
            if tipo_ativo == "Outro":
                tipo_ativo = "CDB"

            # Infer subclasse from indexador
            if indexador == "Prefixado":
                subclasse = "Pré-fixado"
            elif indexador in ("IPCA +",):
                subclasse = "Inflação"
            else:
                subclasse = "Pós-fixado"

            return Asset(
                corretora=BROKER,
                ativo=full_name,
                tipo_ativo=tipo_ativo,
                data_aplicacao=parse_date(data_aplic),
                indexador=indexador,
                taxa=taxa,
                vencimento=parse_date(vencimento),
                liquidez=None,
                valor_aplicado=parse_br(saldo_aplicado),
                valor_bruto=vb,
                valor_liquido=parse_br(saldo_liquido),
                classe=classify_classe(tipo_ativo),
                subclasse=subclasse,
            )
        except Exception as e:
            logger.warning(f"Erro ao parsear linha RF Safra: {row} - {e}")
            return None

    # ------------------------------------------------------------------
    # Detail Fundos table (page 10)
    # ------------------------------------------------------------------
    def _parse_detail_fundos(self, tables: list) -> List[Asset]:
        """Parse Fundos detail table.

        Columns: Fundos | Qtde de Cotas | Valor Cotas | Sld. Aplicado |
                 Sld. Bruto | Impostos | Sld. Líquido
        """
        assets = []
        current_subclasse = "-"

        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = " ".join(header).lower()

            # Identify fundos table: has "cotas" and "bruto"
            if "cota" not in header_lower:
                continue
            if "bruto" not in header_lower and "aplicado" not in header_lower:
                continue
            # Exclude RF detail table (has "indexador")
            if "indexador" in header_lower:
                continue

            col_map = self._build_col_map(header)

            for row in table[1:]:
                if not row or not row[0]:
                    continue
                row_clean = [str(c).strip() if c else "" for c in row]
                nome = row_clean[0]
                if not nome or len(nome) < 2:
                    continue

                lower_nome = nome.lower().strip()
                if lower_nome in CLASS_HEADERS or lower_nome == "fundos":
                    # Could be a subclass header
                    if "renda fixa" in lower_nome:
                        current_subclasse = "Pós-fixado"
                    elif "multimercado" in lower_nome:
                        current_subclasse = "Multimercado"
                    continue
                if "total" in lower_nome:
                    continue
                # Skip date-like names (movimentação rows)
                if re.match(r'^\d{2}/\d{2}/\d{2,4}$', nome.strip()):
                    continue

                saldo_bruto = self._get_col(row_clean, col_map, ["sld. bruto", "bruto"])
                saldo_liquido = self._get_col(row_clean, col_map, ["sld. líquido", "sld. liquido", "líquido"])
                saldo_aplicado = self._get_col(row_clean, col_map, ["sld. aplicado", "aplicado"])

                vb = parse_br(saldo_bruto)
                if vb is None or vb == 0:
                    continue

                tipo_ativo = classify_asset(nome)
                if tipo_ativo == "Outro":
                    tipo_ativo = "Fundo"

                assets.append(Asset(
                    corretora=BROKER,
                    ativo=nome,
                    tipo_ativo=tipo_ativo,
                    data_aplicacao=None,
                    indexador="-",
                    taxa=None,
                    vencimento=None,
                    liquidez=None,
                    valor_aplicado=parse_br(saldo_aplicado),
                    valor_bruto=vb,
                    valor_liquido=parse_br(saldo_liquido),
                    classe="Fundo de Investimento",
                    subclasse=current_subclasse,
                ))

        return assets

    # ------------------------------------------------------------------
    # Detail Ações table (pages 8-9)
    # ------------------------------------------------------------------
    def _parse_detail_acoes(self, tables: list) -> List[Asset]:
        """Parse Ações detail table.

        Look for tables with columns like: Ativo | ... | Sld Bruto | ... | Sld Líquido
        """
        assets = []
        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = " ".join(header).lower()

            # Ações table: has "cotação" or "cotacao" (stock price column)
            if "cotação" not in header_lower and "cotacao" not in header_lower:
                continue
            # Exclude fundos table
            if "cota" in header_lower and "valor cota" in header_lower:
                continue

            col_map = self._build_col_map(header)

            for row in table[1:]:
                if not row or not row[0]:
                    continue
                row_clean = [str(c).strip() if c else "" for c in row]
                nome = row_clean[0]
                if not nome or len(nome) < 2:
                    continue

                lower_nome = nome.lower()
                if lower_nome in CLASS_HEADERS or "total" in lower_nome:
                    continue
                # Skip date-like names (movimentação rows)
                if re.match(r'^\d{2}/\d{2}/\d{2,4}$', nome.strip()):
                    continue

                saldo_bruto = self._get_col(row_clean, col_map, ["sld bruto", "sld. bruto", "bruto"])
                saldo_liquido = self._get_col(row_clean, col_map, ["sld líquido", "sld. líquido", "líquido"])

                vb = parse_br(saldo_bruto)
                if vb is None or vb == 0:
                    continue

                tipo_ativo = classify_asset(nome)
                if tipo_ativo == "Outro":
                    # BDRs end in 34, stocks end in 3/4/11
                    tipo_ativo = "FII" if nome.upper().endswith("11") else "Ação"

                assets.append(Asset(
                    corretora=BROKER,
                    ativo=nome,
                    tipo_ativo=tipo_ativo,
                    data_aplicacao=None,
                    indexador="Renda Variável",
                    taxa=None,
                    vencimento=None,
                    liquidez=None,
                    valor_aplicado=None,
                    valor_bruto=vb,
                    valor_liquido=parse_br(saldo_liquido),
                    classe="Renda Variável",
                    subclasse="Ações",
                ))

        return assets

    # ------------------------------------------------------------------
    # Summary table fallback (Posição de Investimentos)
    # ------------------------------------------------------------------
    def _parse_summary(self, tables: list) -> List[Asset]:
        """Parse summary table: Resumo | Sld Bruto | Impostos | Sld Líquido | ..."""
        assets = []
        current_classe = ""

        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = " ".join(header).lower()

            if "resumo" not in header_lower and "sld bruto" not in header_lower:
                continue

            col_map = self._build_col_map(header)

            for row in table[1:]:
                if not row or not row[0]:
                    continue
                row_clean = [str(c).strip() if c else "" for c in row]
                nome = row_clean[0]
                lower_nome = nome.lower().strip()

                # Class headers
                if lower_nome in CLASS_HEADERS:
                    current_classe = nome
                    continue
                if "total" in lower_nome:
                    continue
                # Skip date-like names (movimentação rows)
                if re.match(r'^\d{2}/\d{2}/\d{2,4}$', nome.strip()):
                    continue

                saldo_bruto = self._get_col(row_clean, col_map, ["sld bruto", "bruto"])
                saldo_liquido = self._get_col(row_clean, col_map, ["sld líquido", "sld. líquido", "líquido"])

                vb = parse_br(saldo_bruto)
                if vb is None or vb == 0:
                    continue

                tipo_ativo = classify_asset(nome)
                if tipo_ativo == "Outro":
                    tipo_ativo = "Fundo"

                assets.append(Asset(
                    corretora=BROKER,
                    ativo=nome,
                    tipo_ativo=tipo_ativo,
                    data_aplicacao=None,
                    indexador="-",
                    taxa=None,
                    vencimento=None,
                    liquidez=None,
                    valor_aplicado=None,
                    valor_bruto=vb,
                    valor_liquido=parse_br(saldo_liquido),
                    classe=classify_classe(tipo_ativo),
                    subclasse="-",
                ))

        return assets

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_taxa_safra(indexador_raw: str, pct_index: str, taxa_aa: str) -> Tuple[str, Optional[float]]:
        """Parse Safra's split taxa columns.

        Rules:
        - PRE + taxa_aa → Prefixado, taxa_value
        - CDI + %indexador → % CDI, pct_value
        - CDI + taxa_aa → CDI +, taxa_value
        - IPCA + taxa_aa → IPCA +, taxa_value
        """
        idx = indexador_raw.upper().strip() if indexador_raw else ""
        pct = pct_index.strip() if pct_index else ""
        taxa = taxa_aa.strip() if taxa_aa else ""

        # Clean taxa value (remove +/- prefix)
        def parse_val(s: str) -> Optional[float]:
            s = s.replace("+", "").replace("-", "").strip()
            if not s or s == "-":
                return None
            val = parse_br(s)
            return val

        if idx == "PRE":
            return "Prefixado", parse_val(taxa)

        if idx == "CDI":
            if pct and pct != "-":
                return "% CDI", parse_val(pct)
            if taxa and taxa != "-":
                return "CDI +", parse_val(taxa)
            return "% CDI", 100.0

        if idx == "IPCA":
            if taxa and taxa != "-":
                return "IPCA +", parse_val(taxa)
            return "IPCA +", 0.0

        if idx == "SELIC":
            return "% CDI", parse_val(pct) if pct and pct != "-" else 100.0

        return "-", None

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
