"""Orquestrador: detecta corretora, extrai dados, consolida."""

import logging
import os
from typing import Callable, List, Optional

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
    """Extrai texto completo do PDF usando PyMuPDF."""
    from utils.pdf_reader import extract_text
    return extract_text(pdf_path)


def process_pdfs_with_callback(
    pdf_paths: List[str],
    output_path: str,
    ref_date: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """Versão do process_pdfs que reporta progresso via callback (para GUI)."""
    log = log_callback or print

    plugins = discover_plugins()
    log(f"Plugins carregados: {', '.join(p.broker_name() for p in plugins)}")

    all_assets: List[Asset] = []

    for pdf_path in pdf_paths:
        basename = os.path.basename(pdf_path)
        log(f"Processando: {basename}...")

        try:
            text = _extract_text(pdf_path)
        except Exception as e:
            log(f"  Erro ao ler: {e}")
            continue

        matched = False
        for plugin_class in plugins:
            try:
                if plugin_class.detect(text):
                    log(f"  {plugin_class.broker_name()} detectado")
                    plugin = plugin_class()
                    extracted = plugin.extract(pdf_path)
                    log(f"  {len(extracted)} ativos extraidos")
                    all_assets.extend(extracted)
                    matched = True
                    break
            except Exception as e:
                log(f"  Erro no plugin {plugin_class.broker_name()}: {e}")

        if not matched:
            log(f"  PDF nao reconhecido - pulando")

    if all_assets:
        corretoras = len(set(a.corretora for a in all_assets))
        export_excel(all_assets, output_path, ref_date)
        log(f"\n{len(all_assets)} ativos de {corretoras} corretora(s) consolidados!")
        return True
    else:
        log("\nNenhum ativo encontrado nos PDFs fornecidos.")
        return False


def list_plugins():
    """Lista plugins disponíveis."""
    plugins = discover_plugins()
    print("Plugins disponíveis:")
    for p in plugins:
        print(f"  - {p.broker_name()}")
