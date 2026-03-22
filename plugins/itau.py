"""Plugin para Itaú Personnalité — extrai de tabelas pág 6-7."""

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
    "previdência": "Previdência",
    "previdencia": "Previdência",
}

# Class header names to skip (sections, not assets)
CLASS_HEADERS = {
    "renda fixa", "renda variável", "renda variavel",
    "previdência", "previdencia", "ações", "acoes",
    "multimercados", "multimercado",
    "total", "total da carteira", "total geral",
}

# Garbage names that appear in Itaú tables but are not asset names
_GARBAGE_NAMES = {
    # Risk levels
    "alto", "médio", "medio", "baixo", "moderado",
    # Generic fragments
    "meses", "mês", "mes", "anos", "ano",
    "de um fundo", "de um", "do fundo",
    "sim", "não", "nao",
    # Column headers that leak as data
    "produto", "saldo", "aplicação", "aplicacao",
    "vencto", "taxa contrat", "partic carteira",
    "risco", "liquidez", "resgate",
    # Section labels
    "sua carteira detalhada", "sua carteira",
    "carteira de investimentos",
}

# Lines to skip
SKIP_PATTERNS = (
    "% do cdi", "% do ibovespa", "retorno sobre o ifix",
    "retorno sobre o ipca", "retorno sobre", "% cdi",
    "total da carteira", "total",
)


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
            from utils.pdf_reader import extract_from_pdf
            full_text, all_tables = extract_from_pdf(pdf_path)
            assets = self._parse_tables(all_tables)
        except Exception as e:
            logger.warning(f"Erro ao processar Itau PDF {pdf_path}: {e}")

        return assets

    def _parse_tables(self, tables: list) -> List[Asset]:
        """Parse all tables looking for asset position tables.

        Itaú tables on pages 6-7 have headers like:
        [None, 'Sld Bruto (R$)', 'Impostos (R$)', 'Sld Líquido (R$)', '% PL', ...]
        or
        ['Produto', 'Saldo', 'Aplicação', 'Vencto', 'Taxa Contrat.', ...]

        Data rows have asset names or class headers (RENDA FIXA, PREVIDÊNCIA).
        """
        assets = []
        current_subclasse = "-"
        current_classe = "Renda Fixa"

        for table in tables:
            if not table or not table[0]:
                continue

            header = [str(c).strip() if c else "" for c in table[0]]
            header_lower = " ".join(header).lower()

            # Detect position tables by header keywords
            is_position_table = False
            if "sld bruto" in header_lower or "saldo bruto" in header_lower:
                is_position_table = True
            elif "produto" in header_lower and ("saldo" in header_lower or "bruto" in header_lower):
                is_position_table = True

            if not is_position_table:
                continue

            col_map = {}
            for i, h in enumerate(header):
                col_map[h.lower().strip()] = i

            for row in table[1:]:
                if not row:
                    continue

                row_clean = [str(c).strip() if c else "" for c in row]

                # Find the name — first non-empty cell
                nome = ""
                for cell in row_clean:
                    if cell and len(cell) >= 2:
                        nome = cell
                        break

                if not nome:
                    continue

                lower_nome = nome.lower().strip()

                # Skip benchmark/return lines
                if any(lower_nome.startswith(p) for p in SKIP_PATTERNS):
                    continue

                # Detect class/subclass headers
                is_class_header = False
                for key, val in SUBCLASSE_MAP.items():
                    if key in lower_nome:
                        current_subclasse = val
                        is_class_header = True
                        # Also set classe
                        if "renda variável" in lower_nome or "renda variavel" in lower_nome or "ações" in lower_nome:
                            current_classe = "Renda Variável"
                        elif "previdência" in lower_nome or "previdencia" in lower_nome:
                            current_classe = "Previdência"
                        elif "multimercado" in lower_nome:
                            current_classe = "Fundo de Investimento"
                        else:
                            current_classe = "Renda Fixa"
                        break

                if is_class_header:
                    continue

                # Skip known class headers and totals
                if lower_nome in CLASS_HEADERS:
                    continue
                if "total" in lower_nome:
                    continue

                # Also detect section headers with percentage prefix
                # e.g. "48,8% Juros pós-fixados"
                section_match = re.match(r'^[\d,]+%?\s+(.+)', lower_nome)
                if section_match:
                    rest = section_match.group(1).strip()
                    for key, val in SUBCLASSE_MAP.items():
                        if key in rest:
                            current_subclasse = val
                            is_class_header = True
                            break
                    if is_class_header:
                        continue

                # Filter garbage names
                if self._is_garbage_name(nome):
                    continue

                # Extract values
                asset = self._parse_asset_row(row_clean, col_map, nome,
                                              current_classe, current_subclasse)
                if asset:
                    assets.append(asset)

        return assets

    def _parse_asset_row(self, row: list, col_map: dict, nome: str,
                         classe: str, subclasse: str) -> Optional[Asset]:
        try:
            def get_col(keywords, default=""):
                for kw in keywords:
                    for h, idx in col_map.items():
                        if kw in h:
                            if idx < len(row):
                                return row[idx]
                return default

            saldo_bruto = get_col(["sld bruto", "saldo bruto", "saldo"])
            saldo_liquido = get_col(["sld líquido", "sld liquido", "saldo líquido"])
            aplic = get_col(["aplicação", "aplicacao", "aplic"])
            vencto = get_col(["vencto", "venc"])
            taxa_raw = get_col(["taxa contrat", "taxa"])

            vb = parse_br(saldo_bruto)
            if vb is None or vb == 0:
                # Try finding numeric values positionally
                nums = []
                for i, cell in enumerate(row[1:], 1):
                    val = parse_br(cell)
                    if val is not None and val > 100:
                        nums.append((i, val))
                if nums:
                    vb = nums[0][1]
                else:
                    return None

            if vb is None or vb == 0:
                return None

            vl = parse_br(saldo_liquido)

            indexador, taxa = parse_tax(taxa_raw) if taxa_raw and taxa_raw.strip() not in ("", "-") else ("-", None)
            tipo_ativo = classify_asset(nome)

            upper_name = nome.upper()

            # Reclassificação especial Itaú
            if any(k in upper_name for k in ["GANHO GARANTI", "NASDAQ", "SP 500"]):
                tipo_ativo = "COE"
                classe = "COE"
                subclasse = "Alternativo"
            elif tipo_ativo == "FII":
                classe = "Renda Variável"
                subclasse = "Renda Variável"
            elif tipo_ativo == "Previdência":
                classe = "Previdência"
                subclasse = "Previdência PGBL" if "PGBL" in upper_name else "Previdência VGBL"
            elif tipo_ativo == "Fundo":
                classe = "Fundo de Investimento"
            elif tipo_ativo == "Outro":
                tipo_ativo = "CDB"
                classe = "Renda Fixa"
            else:
                classe = classify_classe(tipo_ativo)

            # Inferir indexador da subclasse se não encontrado
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
                data_aplicacao=parse_date(aplic) if aplic and aplic.strip() not in ("", "-") else None,
                indexador=indexador,
                taxa=taxa,
                vencimento=parse_date(vencto) if vencto and vencto.strip() not in ("", "-") else None,
                liquidez=None,
                valor_aplicado=None,
                valor_bruto=vb,
                valor_liquido=vl,
                classe=classe,
                subclasse=subclasse,
            )

        except Exception as e:
            logger.warning(f"Erro ao parsear linha Itaú: {row} - {e}")
            return None

    @staticmethod
    def _is_garbage_name(nome: str) -> bool:
        """Filter out garbage names that are not real asset names."""
        if not nome or len(nome) < 2:
            return True
        lower = nome.lower().strip()
        # Exact match against known garbage
        if lower in _GARBAGE_NAMES:
            return True
        # Too short — likely metadata fragment
        if len(lower) <= 3 and not re.search(r'[A-Z]{2,}', nome):
            return True
        # Pure date
        if re.match(r'^\d{2}/\d{2}/\d{2,4}$', nome.strip()):
            return True
        # Pure number or percentage
        if re.match(r'^[\d.,\-%]+$', nome.strip()):
            return True
        # Single common word that's not an asset
        single_word_garbage = {"alto", "médio", "medio", "baixo", "moderado",
                               "meses", "mês", "mes", "anos", "ano", "sim", "não", "nao",
                               "d+0", "d+1", "d+2", "d+30", "d+31", "d+32",
                               "diário", "diario", "mensal", "anual",
                               "resgate", "liquidez", "risco"}
        if lower in single_word_garbage:
            return True
        # Fragment patterns: "de um fundo", "do fundo", etc.
        if re.match(r'^(de |do |da |dos |das |um |uma |no |na )', lower):
            return True
        return False
