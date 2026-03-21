"""Fallback: parseia texto bruto do Relatório de Performance BTG/ONE.

O texto do PDF vem com cada campo em linhas SEPARADAS. Este parser
agrupa linhas em blocos (nome + dados) e extrai os campos por padrão.
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

BROKER = "BTG Pactual"

# Linhas que devem ser ignoradas (não são nome de ativo)
_SKIP_PATTERNS = re.compile(
    r'^(Ativo|TOTAL|Total|Patrimônio|Distribuição|Em\s|'
    r'Os principais|Saldo Bruto|Percentual|A rentabilidade|'
    r'Mês Atual|Ano|Desde|No Período|Benchmarks?|'
    r'% do CDI|Saldo bruto|Preço médio|Saldo líquido|Valor aplicado|'
    r'Data Inicial|Quantidade|Vencimento|Taxa|Resgate|Preço)\b',
    re.IGNORECASE
)

# Lines that are taxa continuations, not asset names
_TAXA_KEYWORDS = re.compile(
    r'^(a\.a\.$|CDI\b|IPCA\b|% do CDI|%\s*CDI\b|PRE\b)',
    re.IGNORECASE
)


def _is_asset_name(line: str) -> bool:
    """Determina se uma linha é um nome de ativo (início de bloco)."""
    if not line or len(line) < 3:
        return False
    # Must contain letters
    if not re.search(r'[A-Za-z]', line):
        return False
    # Exclude known non-name patterns
    if _SKIP_PATTERNS.match(line):
        return False
    if _TAXA_KEYWORDS.match(line):
        return False
    # Exclude lines that are just R$ values, dates, numbers, or dashes
    if line.startswith('R$') or line == '-':
        return False
    if re.match(r'^\d{2}/\d{2}/\d{4}$', line):
        return False
    if re.match(r'^[\d.,]+%?\s*(a\.a\.)?$', line):
        return False
    # Exclude D+NN (liquidez)
    if re.match(r'^D\+\d+$', line):
        return False
    # Subclasse headers (Pré-fixado R$ ..., Pós-fixado R$ ...)
    if re.match(r'^(Pré|Pós|Inflação|Alternativo|Renda\s+Variável|Renda\s+Fixa|'
                r'Retorno\s+Absoluto|Multimercado|Cambial)\b', line):
        return False
    return True


class BTGTextParser:
    """Parser de texto bruto para Relatório de Performance BTG.

    Usado como fallback quando o plugin BTG detecta o PDF mas as tabelas
    extraídas vêm com colunas concatenadas (0 ativos via tabela).
    """

    BROKER = BROKER

    @staticmethod
    def can_handle(text: str) -> bool:
        lower = text.lower()
        return ("relatório de performance" in lower or "relatório\nde performance" in lower) and \
               ("btg" in lower or "one" in lower or "btgpactual" in lower)

    def extract_from_text(self, full_text: str) -> List[Asset]:
        assets: List[Asset] = []

        # Split into major sections
        lines = full_text.split('\n')

        # Find section boundaries
        rf_start, rf_end = self._find_section(lines, 'em renda fixa')
        fundo_start, fundo_end = self._find_section(lines, 'em fundo de investimento')
        rv_start, rv_end = self._find_section(lines, 'em renda variável')

        if rf_start is not None:
            assets.extend(self._parse_section_rf(lines[rf_start:rf_end]))
        if fundo_start is not None:
            assets.extend(self._parse_section_fundos(lines[fundo_start:fundo_end]))
        if rv_start is not None:
            assets.extend(self._parse_section_rv(lines[rv_start:rv_end]))

        return assets

    @staticmethod
    def _find_section(lines: list, marker: str) -> Tuple[Optional[int], int]:
        """Find start and end of a section. End is the next section or stop marker."""
        start = None
        for i, line in enumerate(lines):
            lower = line.strip().lower()
            if marker in lower:
                start = i
                continue
            if start is not None:
                # End at next major section or at rentabilidade section
                if any(m in lower for m in [
                    'em renda fixa', 'em fundo de investimento',
                    'em renda variável', 'em coe',
                    'a rentabilidade completa', 'saldo bruto (r$) percentual',
                ]) and i > start:
                    return start, i
        return start, len(lines) if start is not None else 0

    # ------------------------------------------------------------------
    # Renda Fixa
    # ------------------------------------------------------------------
    def _parse_section_rf(self, section_lines: list) -> List[Asset]:
        assets: List[Asset] = []
        current_subclasse = "-"

        # Collect blocks: each block = [name_lines..., data_lines...]
        blocks = self._split_into_blocks(section_lines, current_subclasse)

        for block_lines, subclasse in blocks:
            asset = self._parse_rf_block(block_lines, subclasse)
            if asset:
                assets.append(asset)

        return assets

    def _split_into_blocks(self, section_lines: list, default_subclasse: str):
        """Split section lines into (block_lines, subclasse) tuples."""
        blocks = []
        current_block: List[str] = []
        current_subclasse = default_subclasse

        for line_raw in section_lines:
            line = line_raw.strip()
            if not line:
                continue

            # Detect subclasse change
            sub_match = re.match(
                r'^(Pré-?[Ff]ixado|Pós-?[Ff]ixado|Inflação|Alternativo|'
                r'Renda\s+Variável|Renda\s+Fixa|'
                r'Retorno\s+Absoluto\s*\(?\s*MM\s*\)?|Multimercado|Cambial)',
                line
            )
            if sub_match:
                # Emit previous block
                if current_block:
                    blocks.append((current_block, current_subclasse))
                    current_block = []
                raw_sub = sub_match.group(1).strip()
                # Normalize
                if 'Pré' in raw_sub or 'pré' in raw_sub:
                    current_subclasse = "Pré-fixado"
                elif 'Pós' in raw_sub or 'pós' in raw_sub:
                    current_subclasse = "Pós-fixado"
                elif 'Inflação' in raw_sub:
                    current_subclasse = "Inflação"
                elif 'Retorno' in raw_sub or 'Multimercado' in raw_sub:
                    current_subclasse = "Multimercado"
                else:
                    current_subclasse = raw_sub
                continue

            # Skip headers
            if _SKIP_PATTERNS.match(line):
                continue

            # Is this a new asset name?
            if _is_asset_name(line):
                # Emit previous block
                if current_block:
                    blocks.append((current_block, current_subclasse))
                current_block = [line]
            elif current_block:
                # Data line — add to current block
                current_block.append(line)

        # Emit last block
        if current_block:
            blocks.append((current_block, current_subclasse))

        return blocks

    def _parse_rf_block(self, block: list, subclasse: str) -> Optional[Asset]:
        """Parse a Renda Fixa asset block (name + data lines)."""
        if not block:
            return None

        # First line(s) are the name — collect until first data line
        name_parts = []
        data_start = 0
        for i, line in enumerate(block):
            if (re.match(r'^\d{2}/\d{2}/\d{4}$', line) or
                    re.match(r'^[\d.,]+$', line) or
                    line.startswith('R$') or
                    line == '-' or
                    re.match(r'^D\+\d+$', line) or
                    _TAXA_KEYWORDS.match(line)):
                data_start = i
                break
            name_parts.append(line)

        if not name_parts:
            return None

        nome = ' '.join(name_parts).replace('*', '').strip()
        if not nome or len(nome) < 3:
            return None

        # Parse data lines
        dates = []
        r_values = []
        taxa_parts = []
        liquidez = None

        i = data_start
        while i < len(block):
            line = block[i]

            # Date
            if re.match(r'^\d{2}/\d{2}/\d{4}$', line):
                dates.append(line)
            # R$ value
            elif line.startswith('R$'):
                val_match = re.search(r'R\$\s*([\d.,]+)', line)
                if val_match:
                    r_values.append(val_match.group(1))
            # Taxa parts: "15,25%" or "a.a." or "CDI" or "CDI +" or "IPCA +"
            elif re.match(r'^[\d,]+%$', line):
                taxa_parts.append(line)
            elif line.lower() == 'a.a.':
                taxa_parts.append(line)
            elif re.match(r'^CDI\b', line, re.IGNORECASE):
                taxa_parts.append(line)
            elif re.match(r'^IPCA\b', line, re.IGNORECASE):
                taxa_parts.append(line)
            elif re.match(r'^% do CDI$', line, re.IGNORECASE):
                taxa_parts.append(line)
            # Liquidez
            elif re.match(r'^D\+\d+$', line):
                liquidez = line
            # Plain number (quantidade, etc.) — skip
            elif re.match(r'^[\d.,]+$', line):
                pass
            # Dash — skip
            elif line == '-':
                pass

            i += 1

        # Need at least 1 R$ value
        if not r_values:
            return None

        # Map R$ values: saldo_bruto, preço médio (skip), saldo_líquido, valor_aplicado
        # RF has: saldo_bruto | preço_médio | saldo_líquido | valor_aplicado
        # But preço_médio was often "-" (skipped above), so we may have 3 R$ values
        saldo_bruto = parse_br(r_values[0]) if len(r_values) >= 1 else None
        saldo_liquido = parse_br(r_values[1]) if len(r_values) >= 2 else None
        valor_aplicado = parse_br(r_values[2]) if len(r_values) >= 3 else None

        if not saldo_bruto or saldo_bruto == 0:
            return None

        data_aplicacao = dates[0] if dates else None
        vencimento = dates[1] if len(dates) >= 2 else None

        # Build taxa string
        taxa_raw = ' '.join(taxa_parts).strip()
        if taxa_raw.upper() == "CDI":
            indexador, taxa = "% CDI", 100.0
        elif taxa_raw:
            indexador, taxa = parse_tax(taxa_raw)
        else:
            indexador, taxa = "-", None

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            tipo_ativo = "CDB"

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo=tipo_ativo,
            data_aplicacao=parse_date(data_aplicacao) if data_aplicacao else None,
            indexador=indexador,
            taxa=taxa,
            vencimento=parse_date(vencimento) if vencimento else None,
            liquidez=liquidez,
            valor_aplicado=valor_aplicado,
            valor_bruto=saldo_bruto,
            valor_liquido=saldo_liquido,
            classe=classify_classe(tipo_ativo),
            subclasse=subclasse,
        )

    # ------------------------------------------------------------------
    # Fundos de Investimento
    # ------------------------------------------------------------------
    def _parse_section_fundos(self, section_lines: list) -> List[Asset]:
        assets: List[Asset] = []
        blocks = self._split_into_blocks(section_lines, "-")

        for block_lines, subclasse in blocks:
            asset = self._parse_fundo_block(block_lines, subclasse)
            if asset:
                assets.append(asset)

        return assets

    def _parse_fundo_block(self, block: list, subclasse: str) -> Optional[Asset]:
        """Parse a Fundo block."""
        if not block:
            return None

        # Name = first line(s) until data
        name_parts = []
        data_start = 0
        for i, line in enumerate(block):
            if (re.match(r'^\d{2}/\d{2}/\d{4}$', line) or
                    re.match(r'^[\d.,]+$', line) or
                    line.startswith('R$') or
                    line == '-' or
                    re.match(r'^D\+\d+$', line)):
                data_start = i
                break
            name_parts.append(line)

        if not name_parts:
            return None

        nome = ' '.join(name_parts).replace('*', '').strip()
        if not nome or len(nome) < 3:
            return None

        dates = []
        r_values = []
        liquidez = None

        for line in block[data_start:]:
            if re.match(r'^\d{2}/\d{2}/\d{4}$', line):
                dates.append(line)
            elif line.startswith('R$'):
                val_match = re.search(r'R\$\s*([\d.,]+)', line)
                if val_match:
                    r_values.append(val_match.group(1))
            elif re.match(r'^D\+\d+$', line):
                liquidez = line

        if not r_values:
            return None

        saldo_bruto = parse_br(r_values[0]) if len(r_values) >= 1 else None
        saldo_liquido = parse_br(r_values[1]) if len(r_values) >= 2 else None
        valor_aplicado = parse_br(r_values[2]) if len(r_values) >= 3 else None

        if not saldo_bruto or saldo_bruto == 0:
            return None

        data_aplicacao = dates[0] if dates else None

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            tipo_ativo = "Fundo"

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo=tipo_ativo,
            data_aplicacao=parse_date(data_aplicacao) if data_aplicacao else None,
            indexador="-",
            taxa=None,
            vencimento=None,
            liquidez=liquidez,
            valor_aplicado=valor_aplicado,
            valor_bruto=saldo_bruto,
            valor_liquido=saldo_liquido,
            classe="Fundo de Investimento",
            subclasse=subclasse if subclasse else "-",
        )

    # ------------------------------------------------------------------
    # Renda Variável (FIIs, Ações)
    # ------------------------------------------------------------------
    def _parse_section_rv(self, section_lines: list) -> List[Asset]:
        assets: List[Asset] = []
        blocks = self._split_into_blocks(section_lines, "Renda Variável")

        for block_lines, subclasse in blocks:
            asset = self._parse_rv_block(block_lines, subclasse)
            if asset:
                assets.append(asset)

        return assets

    def _parse_rv_block(self, block: list, subclasse: str) -> Optional[Asset]:
        """Parse a Renda Variável (FII/Ação) block."""
        if not block:
            return None

        # Name = first line
        nome = block[0].replace('*', '').strip()
        if not nome or len(nome) < 2:
            return None

        r_values = []
        for line in block[1:]:
            if line.startswith('R$'):
                val_match = re.search(r'R\$\s*([\d.,]+)', line)
                if val_match:
                    r_values.append(val_match.group(1))

        if not r_values:
            return None

        # RV layout: saldo_bruto | preço | preço_médio | valor_aplicado
        saldo_bruto = parse_br(r_values[0]) if len(r_values) >= 1 else None
        valor_aplicado = parse_br(r_values[-1]) if len(r_values) >= 2 else None

        if not saldo_bruto or saldo_bruto == 0:
            return None

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            tipo_ativo = "FII"

        return Asset(
            corretora=BROKER,
            ativo=nome,
            tipo_ativo=tipo_ativo,
            data_aplicacao=None,
            indexador="Renda Variável",
            taxa=None,
            vencimento=None,
            liquidez=None,
            valor_aplicado=valor_aplicado,
            valor_bruto=saldo_bruto,
            valor_liquido=None,
            classe=classify_classe(tipo_ativo),
            subclasse=subclasse if subclasse else "Renda Variável",
        )
