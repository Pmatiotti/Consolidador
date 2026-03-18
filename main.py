#!/usr/bin/env python3
"""Consolidador Universal de Carteiras de Investimento — CLI."""

import argparse
import glob
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.engine import process_pdfs, list_plugins


def main():
    parser = argparse.ArgumentParser(
        description="Consolidador Universal de Carteiras de Investimento",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exemplos:
  python main.py --input relatorio_btg.pdf relatorio_xp.pdf --output carteira.xlsx
  python main.py --input *.pdf --output carteira.xlsx --ref "02/2026"
  python main.py --input *.pdf --output carteira.xlsx --verbose
  python main.py --list-plugins
""",
    )

    parser.add_argument(
        "--input", "-i",
        nargs="+",
        help="Caminho(s) dos PDFs de entrada (aceita glob patterns)",
    )
    parser.add_argument(
        "--output", "-o",
        default="carteira_consolidada.xlsx",
        help="Caminho do arquivo Excel de saída (default: carteira_consolidada.xlsx)",
    )
    parser.add_argument(
        "--ref",
        help="Mês/ano de referência para o resumo (ex: '02/2026')",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Modo verboso com logs detalhados",
    )
    parser.add_argument(
        "--list-plugins",
        action="store_true",
        help="Lista plugins de corretoras disponíveis",
    )

    args = parser.parse_args()

    if args.list_plugins:
        list_plugins()
        return

    if not args.input:
        parser.error("--input é obrigatório (a menos que use --list-plugins)")

    # Expand glob patterns
    pdf_paths = []
    for pattern in args.input:
        expanded = glob.glob(pattern)
        if expanded:
            pdf_paths.extend(expanded)
        else:
            pdf_paths.append(pattern)  # Let it fail with proper error later

    if not pdf_paths:
        print("Nenhum arquivo PDF encontrado.", file=sys.stderr)
        sys.exit(1)

    process_pdfs(pdf_paths, args.output, args.ref, args.verbose)


if __name__ == "__main__":
    main()
