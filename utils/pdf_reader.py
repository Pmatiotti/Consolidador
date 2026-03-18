"""Extração robusta de texto e tabelas de PDFs usando PyMuPDF."""

import logging
from typing import List, Tuple

import fitz

logger = logging.getLogger(__name__)


def extract_from_pdf(pdf_path: str) -> Tuple[str, List[list]]:
    """Extrai texto completo e todas as tabelas de um PDF.

    Tenta extração nativa primeiro. Se o PDF tiver páginas como imagem,
    tenta OCR como fallback (requer Tesseract instalado).

    Returns:
        (texto_completo, lista_de_tabelas)
        Cada tabela é uma lista de listas de strings.
    """
    doc = fitz.open(pdf_path)
    full_text = ""
    all_tables = []

    for page_num, page in enumerate(doc):
        # Extrai texto
        text = page.get_text() or ""

        # Se pouco texto, tenta OCR
        if len(text.strip()) < 50:
            text = _try_ocr(page)

        full_text += text + "\n"

        # Extrai tabelas
        try:
            tabs = page.find_tables()
            for tab in tabs:
                table_data = tab.extract()
                if table_data and len(table_data) > 1:
                    all_tables.append(table_data)
        except Exception as e:
            logger.debug(f"Sem tabelas na pagina {page_num}: {e}")

    doc.close()

    return full_text, all_tables


def extract_text(pdf_path: str) -> str:
    """Extrai apenas o texto completo do PDF (para detecção de corretora)."""
    doc = fitz.open(pdf_path)
    text = ""

    for page in doc:
        page_text = page.get_text() or ""

        if len(page_text.strip()) < 50:
            page_text = _try_ocr(page)

        if page_text:
            text += page_text + "\n"

    doc.close()
    return text


def _try_ocr(page) -> str:
    """Tenta OCR na página. Retorna string vazia se falhar."""
    try:
        tp = page.get_textpage_ocr(language="por", dpi=300)
        text = page.get_text("text", textpage=tp)
        if text and len(text.strip()) > 20:
            logger.debug(f"OCR extraiu {len(text)} caracteres")
            return text
    except Exception as e:
        logger.debug(f"OCR nao disponivel: {e}")
    return ""
