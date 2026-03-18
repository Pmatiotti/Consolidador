# Consolidador Universal de Carteiras de Investimento

Aplicação CLI em Python para consolidar relatórios de posição/performance de múltiplas corretoras em uma planilha Excel padronizada.

## Corretoras suportadas

- **BTG Pactual** (ONE Investimentos)
- **Monte Bravo**
- **XP Investimentos**
- **Bradesco Principal**
- **Itaú Personnalité**

## Instalação

```bash
pip install pdfplumber openpyxl
```

## Uso

```bash
# Processar PDFs e gerar Excel
python main.py --input *.pdf --output carteira.xlsx

# Com mês de referência
python main.py --input *.pdf --output carteira.xlsx --ref "02/2026"

# Modo verboso
python main.py --input *.pdf --output carteira.xlsx --verbose

# Listar plugins disponíveis
python main.py --list-plugins
```

## Testes

```bash
python -m pytest tests/ -v
```

## Adicionar nova corretora

1. Criar `plugins/nova_corretora.py`
2. Herdar de `BrokerPlugin`
3. Implementar `detect()`, `broker_name()`, `extract()`
4. O sistema descobre automaticamente na próxima execução
