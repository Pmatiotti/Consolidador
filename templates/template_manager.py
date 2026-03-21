"""Gerencia templates de mapeamento de colunas para corretoras desconhecidas."""

import json
import logging
import os
import sys
from typing import Dict, List, Optional

from models.asset import Asset
from utils.asset_classifier import classify_asset, classify_classe
from utils.date_parser import parse_date
from utils.number_parser import parse_br
from utils.tax_parser import parse_tax, parse_tax_bradesco

logger = logging.getLogger(__name__)


def _get_templates_dir() -> str:
    """Retorna diretorio de templates, com suporte a PyInstaller frozen."""
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), "templates")
    else:
        return os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "templates", "configs"
        )


class ColumnTemplate:
    """Representa um mapeamento de colunas salvo."""

    def __init__(
        self,
        name: str,
        detection_keywords: List[str],
        column_map: Dict[str, int],
        default_indexador: str = "-",
        default_subclasse: str = "-",
        skip_rows_containing: Optional[List[str]] = None,
    ):
        self.name = name
        self.detection_keywords = detection_keywords
        self.column_map = column_map
        self.default_indexador = default_indexador
        self.default_subclasse = default_subclasse
        self.skip_rows_containing = skip_rows_containing or [
            "total", "subtotal",
        ]

    def detect(self, text: str) -> bool:
        lower = text.lower()
        return all(kw.lower() in lower for kw in self.detection_keywords)

    def apply(self, tables: List[list]) -> List[Asset]:
        """Aplica o template as tabelas extraidas e retorna Assets."""
        assets = []
        for table in tables:
            for row in table:
                if not row or len(row) < 3:
                    continue

                first = str(row[0]).lower().strip() if row[0] else ""
                if any(skip in first for skip in self.skip_rows_containing):
                    continue
                if first in (
                    "ativo", "produto", "codigo", "código", "nome", "",
                ):
                    continue

                asset = self._row_to_asset(row)
                if asset:
                    assets.append(asset)
        return assets

    def _row_to_asset(self, row: list) -> Optional[Asset]:
        try:
            def get(field, default=""):
                idx = self.column_map.get(field)
                if idx is not None and idx < len(row):
                    val = row[idx]
                    return str(val).strip() if val else default
                return default

            nome = get("ativo")
            if not nome or len(nome) < 2:
                return None

            taxa_raw = get("taxa")
            indexador_raw = get("indexador")

            if indexador_raw and taxa_raw:
                indexador, taxa = parse_tax_bradesco(indexador_raw, taxa_raw)
            elif taxa_raw:
                indexador, taxa = parse_tax(taxa_raw)
            else:
                indexador = self.default_indexador
                taxa = None

            saldo_bruto = parse_br(get("saldo_bruto"))
            if not saldo_bruto or saldo_bruto == 0:
                return None

            tipo_ativo = classify_asset(nome)
            if tipo_ativo == "Outro":
                tipo_ativo = "CDB"

            return Asset(
                corretora=self.name,
                ativo=nome,
                tipo_ativo=tipo_ativo,
                data_aplicacao=parse_date(get("data_aplicacao")) if get("data_aplicacao") else None,
                indexador=indexador,
                taxa=taxa,
                vencimento=parse_date(get("vencimento")) if get("vencimento") else None,
                liquidez=get("liquidez") or None,
                valor_aplicado=parse_br(get("valor_aplicado")),
                valor_bruto=saldo_bruto,
                valor_liquido=parse_br(get("saldo_liquido")),
                classe=classify_classe(tipo_ativo),
                subclasse=self.default_subclasse if self.default_subclasse != "-" else "-",
            )
        except Exception as e:
            logger.debug(f"Erro ao aplicar template em linha: {e}")
            return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "detection_keywords": self.detection_keywords,
            "column_map": self.column_map,
            "default_indexador": self.default_indexador,
            "default_subclasse": self.default_subclasse,
            "skip_rows_containing": self.skip_rows_containing,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ColumnTemplate":
        return cls(**data)


def save_template(template: ColumnTemplate):
    templates_dir = _get_templates_dir()
    os.makedirs(templates_dir, exist_ok=True)
    path = os.path.join(templates_dir, f"{_safe_name(template.name)}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(template.to_dict(), f, indent=2, ensure_ascii=False)
    logger.info(f"Template salvo: {path}")


def load_templates() -> List[ColumnTemplate]:
    templates_dir = _get_templates_dir()
    templates = []
    if not os.path.exists(templates_dir):
        return templates
    for filename in sorted(os.listdir(templates_dir)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(templates_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            templates.append(ColumnTemplate.from_dict(data))
        except Exception as e:
            logger.warning(f"Erro ao carregar template {filename}: {e}")
    return templates


def find_matching_template(text: str) -> Optional[ColumnTemplate]:
    for template in load_templates():
        if template.detect(text):
            return template
    return None


def _safe_name(name: str) -> str:
    return "".join(
        c if c.isalnum() or c in " _-" else "_" for c in name
    ).strip().replace(" ", "_")
