"""Fallback: parseia texto bruto do Relatório de Performance BTG/ONE."""

import logging
import re
from typing import List, Optional

from models.asset import Asset
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
from utils.number_parser import parse_br
from utils.tax_parser import parse_tax

logger = logging.getLogger(__name__)

BROKER = "BTG Pactual"


class BTGTextParser:
    """Parser de texto bruto para Relatório de Performance BTG.

    Usado como fallback quando o plugin BTG detecta o PDF mas as tabelas
    extraidas vêm com colunas concatenadas (0 ativos via tabela).
    """

    BROKER = BROKER

    @staticmethod
    def can_handle(text: str) -> bool:
        lower = text.lower()
        return ("relatório de performance" in lower or "relatório\nde performance" in lower) and \
               ("btg" in lower or "one" in lower or "btgpactual" in lower)

    def extract_from_text(self, full_text: str) -> List[Asset]:
        assets: List[Asset] = []
        assets.extend(self._parse_renda_fixa(full_text))
        assets.extend(self._parse_fundos(full_text))
        assets.extend(self._parse_renda_variavel(full_text))
        return assets

    # ------------------------------------------------------------------
    # Renda Fixa
    # ------------------------------------------------------------------
    def _parse_renda_fixa(self, text: str) -> List[Asset]:
        assets: List[Asset] = []
        lines = text.split('\n')
        current_subclasse = "-"
        in_rf = False
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            lower_line = line.lower()

            if 'em renda fixa' in lower_line:
                in_rf = True
                i += 1
                continue

            if in_rf and ('em fundo de investimento' in lower_line
                          or 'em renda variável' in lower_line
                          or 'em coe' in lower_line):
                break

            if not in_rf:
                i += 1
                continue

            # Subclasses
            if re.match(r'^Pré-?[Ff]ixado', line):
                current_subclasse = "Pré-fixado"
                i += 1
                continue
            if re.match(r'^Pós-?[Ff]ixado', line):
                current_subclasse = "Pós-fixado"
                i += 1
                continue
            if line.startswith('Inflação'):
                current_subclasse = "Inflação"
                i += 1
                continue
            if line.startswith('Alternativo'):
                current_subclasse = "Alternativo"
                i += 1
                continue

            # Skip headers / totals
            if re.match(r'^(Ativo|TOTAL|Total)\b', line):
                i += 1
                continue

            # Linha com valores monetários R$
            if 'R$' in line and re.search(r'R\$\s*[\d.,]+', line):
                asset = self._parse_rf_line(lines, i, current_subclasse)
                if asset:
                    assets.append(asset)

            i += 1

        return assets

    def _parse_rf_line(self, lines: list, idx: int, subclasse: str) -> Optional[Asset]:
        line = lines[idx].strip()

        r_values = re.findall(r'R\$\s*([\d.,]+)', line)
        dates = re.findall(r'(\d{2}/\d{2}/\d{4})', line)

        # Taxa: "15,25% a.a.", "CDI + 2,50%", "CDI", "IPCA + 6,80%", etc.
        taxa_match = re.search(
            r'(\d+,\d+%\s*a\.a\.'
            r'|CDI\s*\+\s*[\d,]+%?'
            r'|CDI'
            r'|IPCA\s*\+\s*[\d,]+%?'
            r'|\d+,?\d*%\s*do\s*CDI'
            r'|\d+,?\d*%\s*CDI)',
            line
        )
        taxa_raw = taxa_match.group(1) if taxa_match else ""

        nome = self._find_asset_name_rf(lines, idx, line)
        if not nome:
            return None

        # Map R$ values: saldo_bruto, saldo_liquido, valor_aplicado
        saldo_bruto = parse_br(r_values[0]) if len(r_values) >= 1 else None
        saldo_liquido = parse_br(r_values[1]) if len(r_values) >= 2 else None
        valor_aplicado = parse_br(r_values[2]) if len(r_values) >= 3 else None

        if not saldo_bruto or saldo_bruto == 0:
            return None

        data_aplicacao = dates[0] if len(dates) >= 1 else None
        vencimento = dates[1] if len(dates) >= 2 else None

        # Handle "CDI" alone → "% CDI", 100.0
        if taxa_raw.strip().upper() == "CDI":
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
            ativo=nome.replace('*', '').strip(),
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
        )

    def _find_asset_name_rf(self, lines: list, value_idx: int, current_line: str) -> Optional[str]:
        """Extrai nome do ativo de RF da linha atual e/ou linhas anteriores."""
        # Extract name as everything before the first date (DD/MM/YYYY) or first R$
        name_in_line = None
        date_match = re.search(r'\s+\d{2}/\d{2}/\d{4}', current_line)
        r_match = re.search(r'\s+R\$', current_line)

        # Find the earliest delimiter
        cut_pos = len(current_line)
        if date_match:
            cut_pos = min(cut_pos, date_match.start())
        if r_match:
            cut_pos = min(cut_pos, r_match.start())

        if cut_pos > 2:
            candidate = current_line[:cut_pos].strip()
            if candidate and re.search(r'[A-Za-z]', candidate):
                name_in_line = candidate

        name_parts = []
        # Look at previous lines for name parts
        for j in range(value_idx - 1, max(value_idx - 4, -1), -1):
            prev = lines[j].strip()
            if not prev:
                break
            if 'R$' in prev or re.match(r'^(Pré|Pós|Inflação|Alternativo|Ativo|TOTAL|Total)\b', prev):
                break
            if re.search(r'[A-Za-z]', prev) and not re.match(r'^[\d.,]+$', prev):
                name_parts.insert(0, prev)
            else:
                break

        if name_in_line:
            name_parts.append(name_in_line)

        full_name = ' '.join(name_parts).strip()
        return full_name if full_name else None

    # ------------------------------------------------------------------
    # Fundos de Investimento
    # ------------------------------------------------------------------
    def _parse_fundos(self, text: str) -> List[Asset]:
        assets: List[Asset] = []
        lines = text.split('\n')
        current_subclasse = "-"
        in_fundos = False
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            lower_line = line.lower()

            if 'em fundo de investimento' in lower_line:
                in_fundos = True
                i += 1
                continue

            if in_fundos and ('em renda variável' in lower_line
                              or 'em renda fixa' in lower_line
                              or 'em coe' in lower_line):
                break

            if not in_fundos:
                i += 1
                continue

            # Subclasses for funds — strip R$ summary values
            sub_match = re.match(r'^(Renda\s+(?:Variável|Fixa)|Multimercado|Alternativo|Cambial)', line)
            if sub_match:
                current_subclasse = sub_match.group(1).strip()
                i += 1
                continue

            if re.match(r'^(Ativo|TOTAL|Total)\b', line):
                i += 1
                continue

            # Lines with R$ values
            if 'R$' in line and re.search(r'R\$\s*[\d.,]+', line):
                asset = self._parse_fundo_line(lines, i, current_subclasse)
                if asset:
                    assets.append(asset)

            i += 1

        return assets

    def _parse_fundo_line(self, lines: list, idx: int, subclasse: str) -> Optional[Asset]:
        line = lines[idx].strip()

        r_values = re.findall(r'R\$\s*([\d.,]+)', line)
        dates = re.findall(r'(\d{2}/\d{2}/\d{4})', line)

        # Liquidez: D+NN
        liq_match = re.search(r'D\+(\d+)', line)
        liquidez = liq_match.group(0) if liq_match else None

        nome = self._find_asset_name_fundo(lines, idx, line)
        if not nome:
            return None

        # Fundos: saldo_bruto, saldo_liquido, valor_aplicado
        saldo_bruto = parse_br(r_values[0]) if len(r_values) >= 1 else None
        saldo_liquido = parse_br(r_values[1]) if len(r_values) >= 2 else None
        valor_aplicado = parse_br(r_values[2]) if len(r_values) >= 3 else None

        if not saldo_bruto or saldo_bruto == 0:
            return None

        data_aplicacao = dates[0] if len(dates) >= 1 else None

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            tipo_ativo = "Fundo"

        return Asset(
            corretora=BROKER,
            ativo=nome.replace('*', '').strip(),
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

    def _find_asset_name_fundo(self, lines: list, value_idx: int, current_line: str) -> Optional[str]:
        # Extract name before first date or first R$
        name_in_line = None
        date_match = re.search(r'\s+\d{2}/\d{2}/\d{4}', current_line)
        r_match = re.search(r'\s+R\$', current_line)

        cut_pos = len(current_line)
        if date_match:
            cut_pos = min(cut_pos, date_match.start())
        if r_match:
            cut_pos = min(cut_pos, r_match.start())

        if cut_pos > 2:
            candidate = current_line[:cut_pos].strip()
            if candidate and re.search(r'[A-Za-z]', candidate):
                name_in_line = candidate

        name_parts = []
        for j in range(value_idx - 1, max(value_idx - 4, -1), -1):
            prev = lines[j].strip()
            if not prev:
                break
            if 'R$' in prev or re.match(r'^(Renda|Multimercado|Alternativo|Cambial|Ativo|TOTAL|Total)\b', prev):
                break
            if re.search(r'[A-Za-z]', prev) and not re.match(r'^[\d.,]+$', prev):
                name_parts.insert(0, prev)
            else:
                break

        if name_in_line:
            name_parts.append(name_in_line)

        full_name = ' '.join(name_parts).strip()
        return full_name if full_name else None

    # ------------------------------------------------------------------
    # Renda Variável (FIIs, Ações)
    # ------------------------------------------------------------------
    def _parse_renda_variavel(self, text: str) -> List[Asset]:
        assets: List[Asset] = []
        lines = text.split('\n')
        current_subclasse = "-"
        in_rv = False
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            lower_line = line.lower()

            if 'em renda variável' in lower_line:
                in_rv = True
                i += 1
                continue

            if in_rv and ('em renda fixa' in lower_line
                          or 'em fundo de investimento' in lower_line
                          or 'em coe' in lower_line):
                break

            if not in_rv:
                i += 1
                continue

            # Subclasses — strip R$ summary values
            rv_sub = re.match(r'^(Alternativo|Renda\s+Variável)', line)
            if rv_sub:
                current_subclasse = rv_sub.group(1).strip()
                i += 1
                continue

            if re.match(r'^(Ativo|TOTAL|Total)\b', line):
                i += 1
                continue

            # FIIs/Ações: lines with R$ values
            if 'R$' in line and re.search(r'R\$\s*[\d.,]+', line):
                asset = self._parse_rv_line(lines, i, current_subclasse)
                if asset:
                    assets.append(asset)

            i += 1

        return assets

    def _parse_rv_line(self, lines: list, idx: int, subclasse: str) -> Optional[Asset]:
        line = lines[idx].strip()

        r_values = re.findall(r'R\$\s*([\d.,]+)', line)

        nome = self._find_asset_name_rv(lines, idx, line)
        if not nome:
            return None

        # RV: saldo_bruto, preço (ignorar), preço médio (ignorar), valor_aplicado
        saldo_bruto = parse_br(r_values[0]) if len(r_values) >= 1 else None
        valor_aplicado = parse_br(r_values[-1]) if len(r_values) >= 2 else None

        if not saldo_bruto or saldo_bruto == 0:
            return None

        tipo_ativo = classify_asset(nome)
        if tipo_ativo == "Outro":
            tipo_ativo = "FII"

        classe = classify_classe(tipo_ativo)

        return Asset(
            corretora=BROKER,
            ativo=nome.replace('*', '').strip(),
            tipo_ativo=tipo_ativo,
            data_aplicacao=None,
            indexador="Renda Variável",
            taxa=None,
            vencimento=None,
            liquidez=None,
            valor_aplicado=valor_aplicado,
            valor_bruto=saldo_bruto,
            valor_liquido=None,
            classe=classe,
            subclasse=subclasse if subclasse else "Renda Variável",
        )

    def _find_asset_name_rv(self, lines: list, value_idx: int, current_line: str) -> Optional[str]:
        # Extract name before first numeric quantity or R$
        name_in_line = None
        r_match = re.search(r'\s+R\$', current_line)
        num_match = re.search(r'\s+\d+[.,]\d+\s', current_line)

        cut_pos = len(current_line)
        if r_match:
            cut_pos = min(cut_pos, r_match.start())
        if num_match:
            cut_pos = min(cut_pos, num_match.start())

        if cut_pos > 2:
            candidate = current_line[:cut_pos].strip()
            if candidate and re.search(r'[A-Za-z]', candidate):
                name_in_line = candidate

        name_parts = []
        for j in range(value_idx - 1, max(value_idx - 3, -1), -1):
            prev = lines[j].strip()
            if not prev:
                break
            if 'R$' in prev or re.match(r'^(Alternativo|Renda|Ativo|TOTAL|Total)\b', prev):
                break
            if re.search(r'[A-Za-z]', prev) and not re.match(r'^[\d.,]+$', prev):
                name_parts.insert(0, prev)
            else:
                break

        if name_in_line:
            name_parts.append(name_in_line)

        full_name = ' '.join(name_parts).strip()
        return full_name if full_name else None
