"""Orquestrador: detecta corretora, extrai dados, consolida."""

import logging
import os
from typing import Callable, List, Optional

from core.plugin_loader import discover_plugins
from exporters.excel import export_excel
from models.asset import Asset

logger = logging.getLogger(__name__)

# PDFs que nenhum plugin/template conseguiu processar (para a GUI)
UNPROCESSED_PDFS: List[str] = []


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
            logger.info(f"  -> {len(assets)} ativos extraidos")
            all_assets.extend(assets)
        else:
            logger.info(f"  -> Nenhum ativo extraido")

    if all_assets:
        export_excel(all_assets, output_path, ref_date)
        logger.info(f"Total: {len(all_assets)} ativos consolidados em {output_path}")
    else:
        logger.warning("Nenhum ativo encontrado nos PDFs fornecidos.")


def _process_single_pdf(pdf_path: str, plugins: list) -> List[Asset]:
    """Processa um unico PDF: detecta corretora e extrai ativos."""
    try:
        text = _extract_text(pdf_path)
    except Exception as e:
        logger.warning(f"Erro ao ler PDF {pdf_path}: {e}")
        return []

    # Etapa 1: Tentar plugins
    for plugin_class in plugins:
        try:
            if plugin_class.detect(text):
                logger.info(f"  Corretora detectada: {plugin_class.broker_name()}")
                plugin = plugin_class()
                assets = plugin.extract(pdf_path)
                if assets:
                    return assets
                logger.info(f"  Plugin detectou mas extraiu 0 ativos")
        except Exception as e:
            logger.warning(f"  Erro no plugin {plugin_class.broker_name()}: {e}")
            continue

    # Etapa 2: Tentar templates salvos
    assets = _try_templates(pdf_path, text)
    if assets:
        return assets

    logger.warning(f"  PDF nao reconhecido: {pdf_path} -- pulando")
    return []


def _try_templates(pdf_path: str, text: str) -> List[Asset]:
    """Tenta aplicar templates salvos ao PDF."""
    try:
        from templates.template_manager import find_matching_template
        template = find_matching_template(text)
        if template:
            logger.info(f"  Template encontrado: {template.name}")
            from utils.pdf_reader import extract_from_pdf
            _, tables = extract_from_pdf(pdf_path)
            return template.apply(tables)
    except Exception as e:
        logger.debug(f"  Erro ao tentar templates: {e}")
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
    """Versao do process_pdfs que reporta progresso via callback (para GUI)."""
    global UNPROCESSED_PDFS
    UNPROCESSED_PDFS = []
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

        # Tentar plugins
        assets = _try_plugins_cb(pdf_path, text, plugins, log)

        # Tentar templates
        if not assets:
            assets = _try_templates_cb(pdf_path, text, log)

        if assets:
            log(f"  {len(assets)} ativos extraidos")
            all_assets.extend(assets)
        else:
            log(f"  Nenhum ativo extraido -- disponivel para mapeamento manual")
            UNPROCESSED_PDFS.append(pdf_path)

    if all_assets:
        corretoras = len(set(a.corretora for a in all_assets))
        export_excel(all_assets, output_path, ref_date)
        log(f"\n{len(all_assets)} ativos de {corretoras} corretora(s) consolidados!")
        return True
    else:
        log("\nNenhum ativo encontrado nos PDFs fornecidos.")
        return False


def _try_plugins_cb(pdf_path, text, plugins, log):
    """Tenta plugins com callback de log."""
    for plugin_class in plugins:
        try:
            if plugin_class.detect(text):
                log(f"  {plugin_class.broker_name()} detectado")
                plugin = plugin_class()
                extracted = plugin.extract(pdf_path)
                if extracted:
                    return extracted
                log(f"  Plugin detectou mas extraiu 0 ativos")
        except Exception as e:
            log(f"  Erro no plugin {plugin_class.broker_name()}: {e}")
    return []


def _try_templates_cb(pdf_path, text, log):
    """Tenta templates com callback de log."""
    try:
        from templates.template_manager import find_matching_template
        template = find_matching_template(text)
        if template:
            log(f"  Template encontrado: {template.name}")
            from utils.pdf_reader import extract_from_pdf
            _, tables = extract_from_pdf(pdf_path)
            assets = template.apply(tables)
            if assets:
                return assets
    except Exception as e:
        log(f"  Erro ao tentar templates: {e}")
    return []


def list_plugins():
    """Lista plugins disponiveis."""
    plugins = discover_plugins()
    print("Plugins disponiveis:")
    for p in plugins:
        print(f"  - {p.broker_name()}")
