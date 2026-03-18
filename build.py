"""
Gera Consolidador.exe standalone.
Rodar na máquina de desenvolvimento:
    pip install pyinstaller
    python build.py
"""

import os
import PyInstaller.__main__

args = [
    'gui.py',
    '--onefile',
    '--windowed',
    '--name=Consolidador',
    '--add-data=plugins;plugins',
    '--hidden-import=plugins.btg_pactual',
    '--hidden-import=plugins.monte_bravo',
    '--hidden-import=plugins.xp',
    '--hidden-import=plugins.bradesco',
    '--hidden-import=plugins.itau',
    '--hidden-import=fitz',
    '--hidden-import=pymupdf',
    '--hidden-import=openpyxl',
]

if os.path.exists('assets/icon.ico'):
    args.append('--icon=assets/icon.ico')

PyInstaller.__main__.run(args)
print("\nBuild concluido! Executavel em dist/Consolidador.exe")
