"""Extracao robusta de texto e tabelas de PDFs usando multiplos engines."""

import logging
from typing import List, Tuple

import fitz

logger = logging.getLogger(__name__)


def extract_from_pdf(pdf_path: str) -> Tuple[str, List[list]]:
    """Extrai texto e tabelas usando multiplos engines em cascata."""

    # Sempre extrai texto completo primeiro (PyMuPDF e bom nisso)
    full_text = _extract_text_pymupdf(pdf_path)

    # Engine 1: PyMuPDF find_tables()
    tables = _engine_pymupdf_tables(pdf_path)
    if tables:
        logger.info(f"  Engine PyMuPDF: {len(tables)} tabelas encontradas")
        return full_text, tables

    # Engine 2: pdfplumber (algoritmo diferente, complementar)
    tables = _engine_pdfplumber(pdf_path)
    if tables:
        logger.info(f"  Engine pdfplumber: {len(tables)} tabelas encontradas")
        return full_text, tables

    # Engine 3: PyMuPDF text-based (parse text bruto por posicao)
    tables = _engine_text_columns(pdf_path)
    if tables:
        logger.info(f"  Engine text-columns: {len(tables)} tabelas encontradas")
        return full_text, tables

    # Nenhum engine encontrou tabelas
    logger.warning(f"  Nenhum engine extraiu tabelas de {pdf_path}")
    return full_text, []


def extract_text(pdf_path: str) -> str:
    """Extrai apenas o texto completo do PDF (para deteccao de corretora)."""
    return _extract_text_pymupdf(pdf_path)


# --- Text extraction ---

def _extract_text_pymupdf(pdf_path: str) -> str:
    """Extrai texto completo usando PyMuPDF."""
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
    """Tenta OCR na pagina. Retorna string vazia se falhar."""
    try:
        tp = page.get_textpage_ocr(language="por", dpi=300)
        text = page.get_text("text", textpage=tp)
        if text and len(text.strip()) > 20:
            logger.debug(f"OCR extraiu {len(text)} caracteres")
            return text
    except Exception as e:
        logger.debug(f"OCR nao disponivel: {e}")
    return ""


# --- Engine 1: PyMuPDF find_tables ---

def _engine_pymupdf_tables(pdf_path: str) -> List[list]:
    doc = fitz.open(pdf_path)
    all_tables = []
    for page in doc:
        try:
            tabs = page.find_tables()
            for tab in tabs:
                data = tab.extract()
                if data and len(data) > 1:
                    all_tables.append(data)
        except Exception:
            pass
    doc.close()
    return all_tables


# --- Engine 2: pdfplumber ---

def _engine_pdfplumber(pdf_path: str) -> List[list]:
    try:
        import pdfplumber
        all_tables = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        if table and len(table) > 1:
                            cleaned = []
                            for row in table:
                                cleaned.append(
                                    [str(c) if c else "" for c in row]
                                )
                            all_tables.append(cleaned)
        return all_tables
    except ImportError:
        logger.debug("pdfplumber nao disponivel")
        return []
    except Exception as e:
        logger.debug(f"pdfplumber falhou: {e}")
        return []


# --- Engine 3: Text-based column parser ---

def _engine_text_columns(pdf_path: str) -> List[list]:
    """Extrai dados tabulares do texto bruto usando posicao dos caracteres."""
    try:
        doc = fitz.open(pdf_path)
        all_tables = []

        for page in doc:
            blocks = page.get_text("dict")["blocks"]

            # Agrupa linhas por posicao Y
            lines_by_y = {}
            for block in blocks:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        y = round(span["bbox"][1], 0)
                        if y not in lines_by_y:
                            lines_by_y[y] = []
                        lines_by_y[y].append({
                            "x": span["bbox"][0],
                            "text": span["text"].strip(),
                        })

            sorted_ys = sorted(lines_by_y.keys())
            if len(sorted_ys) < 3:
                continue

            table = []
            for y in sorted_ys:
                spans = sorted(lines_by_y[y], key=lambda s: s["x"])
                row = [s["text"] for s in spans]
                if len(row) >= 3:
                    table.append(row)

            if len(table) > 2:
                all_tables.append(table)

        doc.close()
        return all_tables
    except Exception as e:
        logger.debug(f"Text-columns falhou: {e}")
        return []
