#!/usr/bin/env python3
"""Diagnóstico: extrai texto e tabelas de PDF e mostra resultado do parser."""

import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.DEBUG)

from utils.pdf_reader import extract_from_pdf, extract_text
from core.plugin_loader import discover_plugins
from core.engine import TEXT_PARSERS


def diagnostico(pdf_path: str):
    print(f"\n{'='*80}")
    print(f"DIAGNÓSTICO: {os.path.basename(pdf_path)}")
    print(f"{'='*80}\n")

    # 1. Extract text + tables
    full_text = extract_text(pdf_path)
    _, all_tables = extract_from_pdf(pdf_path)

    # 2. Show text snippet
    print("--- TEXTO (primeiros 3000 chars) ---")
    print(full_text[:3000])
    print(f"\n... (total: {len(full_text)} chars)\n")

    # 3. Show tables
    print(f"--- TABELAS ({len(all_tables)} encontradas) ---")
    for ti, table in enumerate(all_tables):
        if not table:
            continue
        print(f"\nTabela {ti} ({len(table)} linhas):")
        for ri, row in enumerate(table[:10]):
            print(f"  Linha {ri}: {row}")
        if len(table) > 10:
            print(f"  ... ({len(table) - 10} linhas restantes)")

    # 4. Test plugins
    plugins = discover_plugins()
    print(f"\n--- DETECÇÃO DE PLUGINS ---")
    for plugin_class in plugins:
        detected = plugin_class.detect(full_text)
        print(f"  {plugin_class.broker_name()}: {'SIM' if detected else 'não'}")
        if detected:
            print(f"    Extraindo...")
            plugin = plugin_class()
            assets = plugin.extract(pdf_path)
            print(f"    -> {len(assets)} ativos extraídos")
            total = sum(a.valor_bruto or 0 for a in assets)
            print(f"    -> Total bruto: R$ {total:,.2f}")
            for a in assets:
                print(f"       {a.ativo[:50]:50s} bruto={a.valor_bruto:>12,.2f}  liq={str(a.valor_liquido):>12s}  tipo={a.tipo_ativo}")

    # 5. Test text parsers
    print(f"\n--- TEXT PARSERS ---")
    for parser in TEXT_PARSERS:
        can = parser.can_handle(full_text)
        print(f"  {parser.BROKER}: {'SIM' if can else 'não'}")
        if can:
            assets = parser.extract_from_text(full_text)
            print(f"    -> {len(assets)} ativos extraídos")
            total = sum(a.valor_bruto or 0 for a in assets)
            print(f"    -> Total bruto: R$ {total:,.2f}")
            for a in assets:
                print(f"       {a.ativo[:50]:50s} bruto={a.valor_bruto:>12,.2f}  liq={str(a.valor_liquido):>12s}  tipo={a.tipo_ativo}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python diagnostico.py <caminho_pdf>")
        sys.exit(1)
    diagnostico(sys.argv[1])
