"""Orquestrador: detecta corretora, extrai dados, consolida."""

import logging
from typing import List, Optional

import pdfplumber

from core.plugin_loader import discover_plugins
from exporters.excel import export_excel
from models.asset import Asset

logger = logging.getLogger(__name__)


def process_pdfs(pdf_paths: List[str], output_path: str, ref_date: Optional[str] = None, verbose: bool = False):
    """Processa lista de PDFs e gera Excel consolidado."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    plugins = discover_plugins()
    logger.info(f"Plugins carregados: {[p.broker_name() for p in plugins]}")

    all_assets: List[Asset] = []

    for pdf_path in pdf_paths:
        logger.info(f"Processando: {pdf_path}")
        assets = _process_single_pdf(pdf_path, plugins)
        if assets:
            logger.info(f"  → {len(assets)} ativos extraídos")
            all_assets.extend(assets)
        else:
            logger.info(f"  → Nenhum ativo extraído")

    if all_assets:
        export_excel(all_assets, output_path, ref_date)
        logger.info(f"Total: {len(all_assets)} ativos consolidados em {output_path}")
    else:
        logger.warning("Nenhum ativo encontrado nos PDFs fornecidos.")


def _process_single_pdf(pdf_path: str, plugins: list) -> List[Asset]:
    """Processa um único PDF: detecta corretora e extrai ativos."""
    try:
        text = _extract_text(pdf_path)
    except Exception as e:
        logger.warning(f"Erro ao ler PDF {pdf_path}: {e}")
        return []

    for plugin_class in plugins:
        try:
            if plugin_class.detect(text):
                logger.info(f"  Corretora detectada: {plugin_class.broker_name()}")
                plugin = plugin_class()
                return plugin.extract(pdf_path)
        except Exception as e:
            logger.warning(f"  Erro no plugin {plugin_class.broker_name()}: {e}")
            continue

    logger.warning(f"  PDF não reconhecido: {pdf_path} — pulando")
    return []


def _extract_text(pdf_path: str) -> str:
    """Extrai texto completo do PDF usando pdfplumber."""
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


def list_plugins():
    """Lista plugins disponíveis."""
    plugins = discover_plugins()
    print("Plugins disponíveis:")
    for p in plugins:
        print(f"  - {p.broker_name()}")
