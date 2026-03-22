"""Fallback: parseia texto bruto de PDFs XP (Posição Detalhada).

Usado quando o plugin XP detecta o PDF mas pdfplumber devolve tabelas
com colunas concatenadas (0 ativos via tabela).
"""

import logging
import re
from typing import List, Optional, Tuple

from models.asset import Asset
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
from utils.number_parser import parse_br
from utils.tax_parser import parse_tax

logger = logging.getLogger(__name__)

BROKER = "XP"

# Section markers and their subclasses
_SECTION_MAP = {
    "prefixada": "Pré-fixado",
    "pré-fixada": "Pré-fixado",
    "pós-fixada": "Pós-fixado",
    "pos-fixada": "Pós-fixado",
    "inflação": "Inflação",
    "inflacao": "Inflação",
}

# Soft skip markers — skip the line but continue processing
# (these appear in sidebars within investment section pages)
_SKIP_MARKERS = (
    "saldo disponível", "saldo disponivel",
    "patrimônio", "patrimonio", "disclaimer",
    "próximos vencimentos", "proximos vencimentos",
)

# Hard stop markers — end all processing once inside a section
# (these appear only after all investment data has been extracted)
_STOP_MARKERS = (
    "saldo projetado",
)


class XPTextParser:
    """Parser de texto bruto para XP Posição Detalhada.

    Fallback quando plugin XP detecta mas tabelas vêm concatenadas.
    """

    BROKER = BROKER

    @staticmethod
    def can_handle(text: str) -> bool:
        lower = text.lower()
        has_xp = "xp investimentos" in lower
        has_rf = "precificação de renda fixa" in lower or "precificacao de renda fixa" in lower
        # Must NOT be Monte Bravo
        has_mb = "montebravo" in lower or "monte bravo" in lower
        return has_xp and has_rf and not has_mb

    def extract_from_text(self, full_text: str) -> List[Asset]:
        assets: List[Asset] = []
        lines = full_text.split('\n')

        current_section = ""  # "RF", "Fundo", "Previdência", "COE"
        current_subclasse = "-"

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            lower = line.lower()

            # Hard stop markers — end all processing once inside a section
            if current_section and any(m in lower for m in _STOP_MARKERS):
                break

            # Skip markers — ignore these lines but continue processing
            if any(m in lower for m in _SKIP_MARKERS):
                i += 1
                continue

            # Section detection: "8.3% | Pós-Fixada" or "Prefixada" etc.
            section_sub = self._detect_section(lower)
            if section_sub:
                section_type, subclasse = section_sub
                current_section = section_type
                current_subclasse = subclasse
                i += 1
                continue

            # Skip header lines
            if self._is_header_line(lower):
                i += 1
                continue

            # Try to detect asset lines
            # XP RF format: "NOME DO ATIVO - VENCIMENTO dd/mm/aaaa dd/mm/aaaa dd/mm/aaaa TAXA R$ xx.xxx,xx ..."
            # or asset name on one line with data following
            if current_section == "RF" and self._looks_like_rf_asset(line):
                asset, consumed = self._extract_rf_asset(lines, i, current_subclasse)
                if asset:
                    assets.append(asset)
                    i += consumed
                    continue

            if current_section == "Fundo" and self._looks_like_fund_name(line):
                asset, consumed = self._extract_fundo_asset(lines, i, current_subclasse)
                if asset:
                    assets.append(asset)
                    i += consumed
                    continue

            if current_section == "Previdência" and self._looks_like_fund_name(line):
                asset, consumed = self._extract_previdencia_asset(lines, i)
                if asset:
                    assets.append(asset)
                    i += consumed
                    continue

            if current_section == "COE" and self._looks_like_fund_name(line):
                asset, consumed = self._extract_coe_asset(lines, i)
                if asset:
                    assets.append(asset)
                    i += consumed
                    continue

            i += 1

        return assets

    # ------------------------------------------------------------------
    # Section detection
    # ------------------------------------------------------------------
    def _detect_section(self, lower: str) -> Optional[Tuple[str, str]]:
        """Detect section type and subclasse from header line."""
        # "8.3% | Pós-Fixada" pattern
        for key, sub in _SECTION_MAP.items():
            if key in lower:
                return "RF", sub

        if "fundos de renda fixa" in lower or "fundos renda fixa" in lower:
            return "Fundo", "Fundos RF Pós"
        if "fundos multimercado" in lower:
            return "Fundo", "Fundos Multimercado"
        if "fundos alternativo" in lower:
            return "Fundo", "Fundos Alternativos"
        if "fundo de investimento" in lower or "fundos de investimento" in lower:
            return "Fundo", "Multimercado"
        if "previdência" in lower or "previdencia" in lower:
            return "Previdência", "Previdência VGBL"
        if lower.strip() == "coe":
            return "COE", "Alternativo"

        return None

    @staticmethod
    def _is_header_line(lower: str) -> bool:
        headers = (
            "ativo", "aplicação", "aplicacao", "carência", "carencia",
            "vencimento", "taxa de compra", "disponível", "disponivel",
            "garantia", "bloqueio", "valor aplicado", "posição", "posicao",
            "valor líquido", "valor liquido", "data cota", "qtd cotas",
            "plano", "tributação", "tributacao", "emissor",
            # Fund/COE column headers and metadata
            "preço", "preco", "qtd.", "qtd ", "valor aplic",
            "data aplica", "data de aplica",
            "data de refer", "data refer",
            "em cotização", "em cotizacao", "valor cota", "qtd cotas",
            # Spaced page headers (e.g. "P O S I Ç Ã O  C O N S O L I D A D A")
            "p o s i", "p r ó", "p r o x",
            # Section/page labels that are not fund names
            "precificação", "precificacao", "título", "titulo",
        )
        return any(lower.startswith(h) for h in headers) and len(lower) < 80

    @staticmethod
    def _looks_like_rf_asset(line: str) -> bool:
        if not line or len(line) < 5:
            return False
        if not re.search(r'[A-Za-z]', line):
            return False
        # RF assets typically start with CDB, LCA, LCI, CRA, CRI, DEB, etc.
        # or contain " - " separator (e.g. "CDB WILL FINANCEIRA (MASTER) - DEZ/2027")
        upper = line.upper()
        rf_prefixes = ("CDB", "LCA", "LCI", "CRA", "CRI", "DEB", "LIG",
                       "LCD", "LF ", "NTN", "CDCA", "CPR")
        if any(upper.startswith(p) for p in rf_prefixes):
            return True
        # Also match if line contains dates and R$ (inline data)
        if re.search(r'\d{2}/\d{2}/\d{4}', line) and "R$" in line:
            return True
        return False

    @staticmethod
    def _looks_like_fund_name(line: str) -> bool:
        if not line or len(line) < 5:
            return False
        if not re.search(r'[A-Za-z]', line):
            return False
        if line.startswith('R$') or line == '-':
            return False
        upper = line.upper()
        skip = ("ATIVO", "TOTAL", "PATRIMÔNIO", "PATRIMONIO", "SALDO",
                "APLICAÇÃO", "APLICACAO", "POSIÇÃO", "POSICAO")
        return not any(upper.startswith(s) for s in skip)

    # ------------------------------------------------------------------
    # RF extraction
    # ------------------------------------------------------------------
    def _extract_rf_asset(self, lines: list, start: int,
                          subclasse: str) -> Tuple[Optional[Asset], int]:
        """Extract RF asset. Data may be on same line or following lines."""
        line = lines[start].strip()

        # Try inline format: "NOME dd/mm/aaaa dd/mm/aaaa dd/mm/aaaa TAXA ... R$ xx R$ yy"
        dates = re.findall(r'\d{2}/\d{2}/\d{4}', line)
        r_values = re.findall(r'R\$\s*([\d.,]+)', line)

        # Extract name (everything before first date or R$)
        name = line
        first_date_match = re.search(r'\d{2}/\d{2}/\d{4}', line)
        if first_date_match:
            name = line[:first_date_match.start()].strip()

        # Extract taxa from inline text
        taxa_match = re.search(r'([\d,]+%\s*CDI|CDI\s*\+?\s*[\d,]+%|IPCA\s*\+?\s*[\d,]+%|[\d,]+%\s*a\.a\.|[\d,]+%)', line)
        taxa_raw = taxa_match.group(0) if taxa_match else ""

        # If no inline data, collect from following lines
        consumed = 1
        if not r_values:
            for j in range(start + 1, min(start + 15, len(lines))):
                next_line = lines[j].strip()
                lower_next = next_line.lower()

                # Stop at next section or asset
                if self._detect_section(lower_next):
                    break
                if self._looks_like_rf_asset(next_line) and j > start + 1:
                    break
                # Don't break on rate/index strings (e.g. "113,00% CDI", "IPC-A +5%")
                is_rate_line = (
                    re.match(r'^[\d,]+%', next_line) or
                    re.match(r'^[\+\-]?[\d,]+%', next_line) or
                    re.match(r'^IPC[-A-Z]', next_line, re.IGNORECASE) or
                    next_line.lower().strip() in ('cdi', 'ipca', 'ipc-a', 'a.a.', 'pré', 'pre') or
                    ('cdi' in next_line.lower() and '%' in next_line) or
                    ('ipca' in next_line.lower() and ('+' in next_line or '%' in next_line)) or
                    ('ipc-a' in next_line.lower() and ('+' in next_line or '%' in next_line))
                )
                if not is_rate_line and self._looks_like_fund_name(next_line) and j > start + 3:
                    break

                consumed += 1

                if re.match(r'^\d{2}/\d{2}/\d{4}$', next_line):
                    dates.append(next_line)
                elif next_line.startswith('R$'):
                    val_match = re.search(r'R\$\s*([\d.,]+)', next_line)
                    if val_match:
                        r_values.append(val_match.group(1))
                elif re.match(r'^[\d,]+%', next_line) or next_line.lower() in ('cdi', 'ipca', 'a.a.'):
                    taxa_raw += " " + next_line

        if not r_values:
            return None, 1

        # Map values: posição (bruto), valor líquido are last two R$ values
        saldo_bruto = parse_br(r_values[-2]) if len(r_values) >= 2 else parse_br(r_values[-1])
        saldo_liquido = parse_br(r_values[-1]) if len(r_values) >= 2 else None
        valor_aplicado = parse_br(r_values[0]) if len(r_values) >= 3 else None

        if not saldo_bruto or saldo_bruto == 0:
            return None, consumed

        # Parse taxa
        indexador, taxa = parse_tax(taxa_raw.strip()) if taxa_raw.strip() else ("-", None)

        data_aplicacao = dates[0] if dates else None
        vencimento = dates[-1] if len(dates) >= 2 else (dates[0] if dates else None)
        if len(dates) >= 2:
            data_aplicacao = dates[0]

        tipo_ativo = classify_asset(name)
        if tipo_ativo == "Outro":
            tipo_ativo = "CDB"

        return Asset(
            corretora=BROKER,
            ativo=name,
            tipo_ativo=tipo_ativo,
            data_aplicacao=parse_date(data_aplicacao) if data_aplicacao else None,
            indexador=indexador,
            taxa=taxa,
            vencimento=parse_date(vencimento) if vencimento else None,
            liquidez=None,
            valor_aplicado=valor_aplicado,
            valor_bruto=saldo_bruto,
            valor_liquido=saldo_liquido,
            classe=classify_classe(tipo_ativo),
            subclasse=subclasse,
        ), consumed

    # ------------------------------------------------------------------
    # Fundo extraction
    # ------------------------------------------------------------------
    def _extract_fundo_asset(self, lines: list, start: int,
                             subclasse: str) -> Tuple[Optional[Asset], int]:
        """Extract fund asset from text lines."""
        nome = lines[start].strip()
        r_values = []
        consumed = 1

        for j in range(start + 1, min(start + 10, len(lines))):
            next_line = lines[j].strip()
            lower_next = next_line.lower()

            if self._detect_section(lower_next):
                break
            if self._looks_like_fund_name(next_line) and r_values:
                break

            consumed += 1

            if next_line.startswith('R$'):
                val_match = re.search(r'R\$\s*([\d.,]+)', next_line)
                if val_match:
                    r_values.append(val_match.group(1))

        if not r_values:
            return None, 1

        saldo_bruto = parse_br(r_values[-2]) if len(r_values) >= 2 else parse_br(r_values[-1])
        saldo_liquido = parse_br(r_values[-1]) if len(r_values) >= 2 else None

        if not saldo_bruto or saldo_bruto == 0:
            return None, consumed

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            tipo_ativo = "Fundo"

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
            classe=classify_classe(tipo_ativo),
            subclasse=subclasse,
        ), consumed

    # ------------------------------------------------------------------
    # Previdência extraction
    # ------------------------------------------------------------------
    def _extract_previdencia_asset(self, lines: list, start: int) -> Tuple[Optional[Asset], int]:
        """Extract previdência asset."""
        nome = lines[start].strip()
        r_values = []
        consumed = 1

        for j in range(start + 1, min(start + 10, len(lines))):
            next_line = lines[j].strip()
            lower_next = next_line.lower()

            if self._detect_section(lower_next):
                break
            if self._looks_like_fund_name(next_line) and r_values:
                break

            consumed += 1

            if next_line.startswith('R$'):
                val_match = re.search(r'R\$\s*([\d.,]+)', next_line)
                if val_match:
                    r_values.append(val_match.group(1))

        if not r_values:
            return None, 1

        saldo_bruto = parse_br(r_values[0])
        if not saldo_bruto or saldo_bruto == 0:
            return None, consumed

        upper_name = nome.upper()
        subclasse = "Previdência PGBL" if "PGBL" in upper_name else "Previdência VGBL"

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo="Previdência",
            data_aplicacao=None,
            indexador="-",
            taxa=None,
            vencimento=None,
            liquidez=None,
            valor_aplicado=None,
            valor_bruto=saldo_bruto,
            valor_liquido=None,
            classe="Previdência",
            subclasse=subclasse,
        ), consumed

    # ------------------------------------------------------------------
    # COE extraction
    # ------------------------------------------------------------------
    def _extract_coe_asset(self, lines: list, start: int) -> Tuple[Optional[Asset], int]:
        """Extract COE asset."""
        nome = lines[start].strip()
        r_values = []
        dates = []
        consumed = 1

        for j in range(start + 1, min(start + 10, len(lines))):
            next_line = lines[j].strip()
            lower_next = next_line.lower()

            if self._detect_section(lower_next):
                break
            if self._looks_like_fund_name(next_line) and r_values:
                break

            consumed += 1

            if next_line.startswith('R$'):
                val_match = re.search(r'R\$\s*([\d.,]+)', next_line)
                if val_match:
                    r_values.append(val_match.group(1))
            elif re.match(r'^\d{2}/\d{2}/\d{4}$', next_line):
                dates.append(next_line)

        if not r_values:
            return None, 1

        # COE columns: Preço (tiny, per unit) | Valor aplicado | Posição
        # Use the largest value = Posição (current position value)
        parsed = [parse_br(v) for v in r_values]
        parsed = [v for v in parsed if v and v > 0]
        if not parsed:
            return None, consumed
        saldo_bruto = max(parsed)
        if not saldo_bruto or saldo_bruto == 0:
            return None, consumed

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo="COE",
            data_aplicacao=parse_date(dates[0]) if dates else None,
            indexador="Alternativo",
            taxa=None,
            vencimento=parse_date(dates[-1]) if len(dates) >= 2 else None,
            liquidez=None,
            valor_aplicado=None,
            valor_bruto=saldo_bruto,
            valor_liquido=saldo_bruto,
            classe="COE",
            subclasse="Alternativo",
        ), consumed
