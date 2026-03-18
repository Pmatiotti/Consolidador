"""Utilitários de limpeza de texto extraído de PDFs."""

import re


def clean_text(text: str) -> str:
    """Remove caracteres problemáticos e normaliza espaços."""
    if not text:
        return ""
    # Normaliza espaços em branco (mantém newlines)
    text = re.sub(r'[^\S\n]+', ' ', text)
    # Remove caracteres de controle exceto newline
    text = re.sub(r'[\x00-\x09\x0b-\x1f\x7f]', '', text)
    return text.strip()


def normalize_whitespace(text: str) -> str:
    """Colapsa múltiplos espaços/newlines em um único espaço."""
    return re.sub(r'\s+', ' ', text).strip()
